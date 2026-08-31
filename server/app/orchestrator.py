# app/orchestrator.py
from __future__ import annotations

import os
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agents import Agent, Runner, FileSearchTool, ModelSettings
from chatkit.agents import AgentContext
from app.viz.radar_html import build_radar_dashboard_html

# =====================================================
# CONFIG
# ===================================================== VECTOR_STORE_ID vs_6a1d49343a688191a1a714ca3dafc3d8  personal vectore  store
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID", "vs_6a116b3869e08191aa26f247b322a8c1")  # api  key labo
# Public base URL of THIS backend (used to build absolute links to /static PDFs).
# Overridden at deploy time with the container's public endpoint.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
KC_GRAPH_PATH = os.getenv("KC_GRAPH_PATH", os.path.join(os.path.dirname(__file__), "kc_graph1.json"))

DIAGNOSTIC_Q_NUM = int(os.getenv("DIAGNOSTIC_Q_NUM", "8"))# global diagnostic length
"""   
PRACTICE_Q_NUM = int(os.getenv("PRACTICE_Q_NUM", "3"))       # per-KC practice length""" 
THRESHOLD = float(os.getenv("MASTERY_THRESHOLD", "0.7"))     # pass threshold (0..1)

PRACTICE_MIN_Q = int(os.getenv("PRACTICE_MIN_Q", "2"))
PRACTICE_MAX_Q = int(os.getenv("PRACTICE_MAX_Q", "14"))
MODULE_THRESHOLD = float(os.getenv("MODULE_THRESHOLD", "0.7"))
MODULE_MIN_Q = int(os.getenv("MODULE_MIN_Q", "8"))
MODULE_MAX_Q = int(os.getenv("MODULE_MAX_Q", "20"))
DIAGNOSTIC_MIN_MASTERY = float(os.getenv("DIAGNOSTIC_MIN_MASTERY", "0.25"))
DIAGNOSTIC_MAX_MASTERY = float(os.getenv("DIAGNOSTIC_MAX_MASTERY", "0.55"))
EVIDENCE_LOG_PATH = os.getenv(
    "EVIDENCE_LOG_PATH",
    os.path.join(os.path.dirname(__file__), "evidence_log.jsonl"),
)
QCM_PROMPT_MAX_CHARS = int(os.getenv("QCM_PROMPT_MAX_CHARS", "240"))
QCM_CHOICE_MAX_CHARS = int(os.getenv("QCM_CHOICE_MAX_CHARS", "90"))

# =====================================================
# HELPERS (extract latest user message text)
# =====================================================
def extract_latest_user_text(input_items: Any) -> str:
    """
    input_items is produced by ThreadItemConverter.to_agent_input(items).
    It's typically a list of message dicts with content blocks.
    """
    if isinstance(input_items, list):
        for msg in reversed(input_items):
            if not isinstance(msg, dict):
                continue
            if msg.get("role") != "user":
                continue
            blocks = msg.get("content", [])
            if not isinstance(blocks, list):
                continue
            for b in blocks:
                if isinstance(b, dict) and b.get("type") == "input_text":
                    t = (b.get("text") or "").strip()
                    if t:
                        return t
            return ""
    return str(input_items or "").strip()


def extract_latest_user_image_urls(input_items: Any) -> List[str]:
    if not isinstance(input_items, list):
        return []
    for msg in reversed(input_items):
        if not isinstance(msg, dict):
            continue
        if msg.get("role") != "user":
            continue
        blocks = msg.get("content", [])
        if not isinstance(blocks, list):
            return []
        urls: List[str] = []
        for b in blocks:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "input_image" and b.get("image_url"):
                urls.append(str(b.get("image_url")))
        return urls
    return []


def looks_like_answers(text: str) -> bool:
    # matches: 1A 2C 3B or 1 a,2 c ...
    return bool(re.search(r"\b\d+\s*[A-D]\b", text.upper()))


def parse_answers_from_text(text: str) -> Dict[int, str]:
    out: Dict[int, str] = {}
    s = text.upper().replace(",", " ")
    for m in re.finditer(r"\b(\d+)\s*([A-D])\b", s):
        out[int(m.group(1))] = m.group(2)
    return out


def fit_qcm_widget_text(text: Any, max_chars: int) -> str:
    """Keep QCM widget labels compact enough for ChatKit radio/text rendering."""
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(clean) <= max_chars:
        return clean

    cut = clean[: max_chars - 1].rstrip()
    for sep in (". ", "; ", ", ", " - ", " "):
        idx = cut.rfind(sep)
        if idx >= max_chars // 2:
            cut = cut[:idx].rstrip()
            break
    return f"{cut}..."


def qcm_widget_data(title: str, questions: List[dict]) -> Dict[str, Any]:
    """
    Builds the dict expected by your qcm widget builder:
    { "title": "...", "questions": [ {id,prompt,choices:[{label,value}]} ] }
    """
    q_out: List[dict] = []
    for q in questions:
        # q["choices"] must be list[str] length 4
        c = q["choices"]
        q_out.append({
            "id": str(q["number"]),
            "prompt": fit_qcm_widget_text(q["text"], QCM_PROMPT_MAX_CHARS),
            "choices": [
                {"label": f"A) {fit_qcm_widget_text(c[0], QCM_CHOICE_MAX_CHARS)}", "value": "A"},
                {"label": f"B) {fit_qcm_widget_text(c[1], QCM_CHOICE_MAX_CHARS)}", "value": "B"},
                {"label": f"C) {fit_qcm_widget_text(c[2], QCM_CHOICE_MAX_CHARS)}", "value": "C"},
                {"label": f"D) {fit_qcm_widget_text(c[3], QCM_CHOICE_MAX_CHARS)}", "value": "D"},
            ],
        })
    return {"title": title, "questions": q_out}




# =====================================================
# KC GRAPH LOADER  (FIXED: leaf KCs + outline order)
# =====================================================
@dataclass
class KCNode:
    id: str
    title: str
    kind: str
    outline_path: List[str] = field(default_factory=list)
    pages: List[int] = field(default_factory=list)


@dataclass
class KcGraph:
    title: str
    nodes: Dict[str, KCNode]
    source_pdf: str = ""

    # raw edges
    next_by_id: Dict[str, str] = field(default_factory=dict)          # sequence edges
    children_by_id: Dict[str, List[str]] = field(default_factory=dict)  # contains edges
    parent_by_id: Dict[str, str] = field(default_factory=dict)

    # computed teaching order
    ordered_kc_ids: List[str] = field(default_factory=list)
    index_by_kc: Dict[str, int] = field(default_factory=dict)

    @staticmethod
    def load(path: str) -> "KcGraph":
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Tolerate common hand-edited JSON issue: trailing commas before ] or }.
            cleaned = re.sub(r",(\s*[\]}])", r"\1", raw)
            data = json.loads(cleaned)

        # ---- nodes
        nodes: Dict[str, KCNode] = {}
        for n in data.get("nodes", []):
            if not isinstance(n, dict):
                continue
            nid = str(n.get("id") or "").strip()
            if not nid:
                continue
            nodes[nid] = KCNode(
                id=nid,
                title=str(n.get("title") or "").strip(),
                kind=str(n.get("kind") or "").strip(),
                outline_path=n.get("outline_path") or [],
                pages=[int(p) for p in (n.get("pages") or []) if isinstance(p, int)],
            )

        # ---- edges: sequence + contains
        # Supports both:
        # 1) legacy: data["edges"] = [{"type":"contains|sequence","src":"...","dst":"..."}]
        # 2) new form: data["contains"] = [[src,dst], ...], data["sequence"] = [[src,dst], ...]
        next_by_id: Dict[str, str] = {}
        children_by_id: Dict[str, List[str]] = {}
        parent_by_id: Dict[str, str] = {}

        def add_contains(src: str, dst: str) -> None:
            if not src or not dst:
                return
            children_by_id.setdefault(src, []).append(dst)
            # assume single parent (outline tree)
            if dst not in parent_by_id:
                parent_by_id[dst] = src

        def add_sequence(src: str, dst: str) -> None:
            if not src or not dst:
                return
            next_by_id[src] = dst

        for e in data.get("edges", []):
            if not isinstance(e, dict):
                continue
            et = str(e.get("type") or "").strip().lower()
            src = str(e.get("src") or "").strip()
            dst = str(e.get("dst") or "").strip()
            if et == "sequence":
                add_sequence(src, dst)
            elif et == "contains":
                add_contains(src, dst)

        for pair in data.get("contains", []):
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            add_contains(str(pair[0] or "").strip(), str(pair[1] or "").strip())

        for pair in data.get("sequence", []):
            if not isinstance(pair, list) or len(pair) < 2:
                continue
            add_sequence(str(pair[0] or "").strip(), str(pair[1] or "").strip())

        g = KcGraph(
            title=str(data.get("title") or data.get("source_title") or "Course").strip(),
            nodes=nodes,
            source_pdf=str(data.get("source_pdf") or "").strip(),
            next_by_id=next_by_id,
            children_by_id=children_by_id,
            parent_by_id=parent_by_id,
        )

        # ---- compute ordered leaf-KCs in outline order
        g.ordered_kc_ids = g._compute_ordered_teachable_kcs()
        g.index_by_kc = {kc_id: i for i, kc_id in enumerate(g.ordered_kc_ids)}
        return g

    # --------------------------
    # Teaching selection: ONLY leaf KCs (no KC/module children)
    # --------------------------
    def _is_teachable_kc(self, nid: str) -> bool:
        n = self.nodes.get(nid)
        return bool(n and n.kind.lower() == "kc")


    # --------------------------
    # Order children using sequence edges when possible
    # --------------------------
    def _ordered_children(self, parent_id: str) -> List[str]:
        kids = [k for k in self.children_by_id.get(parent_id, []) if k in self.nodes]
        if not kids:
            return []

        kidset = set(kids)

        # collect sequence links restricted to this sibling set
        nxt = {k: self.next_by_id[k] for k in kids if self.next_by_id.get(k) in kidset}
        pointed_to = set(nxt.values())

        # start nodes = those not pointed to by others
        starters = [k for k in kids if k not in pointed_to]

        ordered: List[str] = []
        visited: set[str] = set()

        def follow_chain(start: str):
            cur = start
            while cur and cur not in visited:
                visited.add(cur)
                ordered.append(cur)
                cur = nxt.get(cur)

        # follow chains from starters first
        for s in starters:
            follow_chain(s)

        # append any remaining (in original order)
        for k in kids:
            if k not in visited:
                follow_chain(k)

        return ordered

    # --------------------------
    # Compute an outline-ordered list of leaf KCs
    # --------------------------
    def _compute_ordered_teachable_kcs(self) -> List[str]:
        # pick a root: course node if exists, else any node without a parent
        root = None
        for nid, n in self.nodes.items():
            if n.kind.lower() == "course":
                root = nid
                break
        if not root:
            roots = [nid for nid in self.nodes if nid not in self.parent_by_id]
            root = roots[0] if roots else None

        if not root:
            # fallback: all teachable KCs (unordered)
            return [nid for nid in self.nodes if self._is_teachable_kc(nid)]

        out: List[str] = []
        seen: set[str] = set()

        def dfs(node_id: str):
            # ✅ PRE-ORDER: teach the KC first
            if self._is_teachable_kc(node_id) and node_id not in seen:
                seen.add(node_id)
                out.append(node_id)

            # then traverse children in outline order
            for child in self._ordered_children(node_id):
                dfs(child)

        dfs(root)
        return out


    # --------------------------
    # Public API used by Orchestrator
    # --------------------------
    def kc_ids(self) -> List[str]:
        # ONLY teachable leaf KCs, already ordered
        return list(self.ordered_kc_ids)

    def next_kc(self, kc_id: str) -> Optional[str]:
        i = self.index_by_kc.get(kc_id)
        if i is None:
            return None
        j = i + 1
        if j < len(self.ordered_kc_ids):
            return self.ordered_kc_ids[j]
        return None

    def previous_kcs(self, kc_id: str, limit: int = 2, same_module_first: bool = True) -> List[str]:
        i = self.index_by_kc.get(kc_id)
        if i is None or i <= 0:
            return []
        previous = self.ordered_kc_ids[:i]
        if same_module_first:
            cur_module = self.module_of(kc_id)
            same_module = [pid for pid in previous if self.module_of(pid) == cur_module]
            picked = same_module[-limit:]
            if len(picked) < limit:
                for pid in reversed(previous):
                    if pid not in picked:
                        picked.insert(0, pid)
                    if len(picked) >= limit:
                        break
            return picked[-limit:]
        return previous[-limit:]

    def module_of(self, nid: str) -> Optional[str]:
        """Return the module id that contains this node (KC), using parent_by_id."""
        cur = nid
        while True:
            p = self.parent_by_id.get(cur)
            if not p:
                return None
            pn = self.nodes.get(p)
            if pn and pn.kind.lower() == "module":
                return p
            cur = p


    def module_kcs(self, module_id: str) -> List[str]:
        """Return ordered teachable KCs under a module."""
        if module_id not in self.nodes:
            return []

        out: List[str] = []

        def dfs(nid: str):
            if self._is_teachable_kc(nid):
                out.append(nid)
            for ch in self._ordered_children(nid):
                dfs(ch)

        dfs(module_id)

        # keep in global teaching order
        out_set = set(out)
        return [kc for kc in self.ordered_kc_ids if kc in out_set]

    def module_ids(self) -> List[str]:
        return [nid for nid, n in self.nodes.items() if n.kind.lower() == "module"]
        # --------------------------
    # Radar grouping: modules from outline_path (robust)
    # --------------------------
    def _clean_module_label(self, label: str) -> str:
        return (label or "").strip()

    def module_label_for_kc(self, kc_id: str) -> str:
        """
        Decide module label for a KC using outline_path.
        Falls back to contains-based module if outline_path is missing.
        """
        node = self.nodes.get(kc_id)
        if node and isinstance(node.outline_path, list) and node.outline_path:
            path = [str(x).strip() for x in node.outline_path if str(x).strip()]

            # remove course title if it appears at the beginning
            if path and self.title and path[0].lower() == self.title.lower():
                path = path[1:]

            # module label = first remaining level
            if path:
                return self._clean_module_label(path[0])

        # fallback: use contains-based module node title (your old logic)
        mid = self.module_of(kc_id)
        if mid and mid in self.nodes:
            return self._clean_module_label(self.nodes[mid].title)

        return "Module (Unknown)"

    def module_groups_for_radar(self) -> Dict[str, List[str]]:
        """
        Returns: {module_label: [kc_id, kc_id, ...]} in global teaching order.
        Uses outline_path to group.
        """
        groups: Dict[str, List[str]] = {}
        for kc_id in self.ordered_kc_ids:
            if not self._is_teachable_kc(kc_id):
                continue
            label = self.module_label_for_kc(kc_id)
            groups.setdefault(label, []).append(kc_id)
        return groups
        # --------------------------
    # Radar grouping by "section containers"
    # A container is:
    # - kind in {"module","layer"} OR
    # - kind=="kc" BUT it has children (contains edges)
    # --------------------------
    def _is_container(self, nid: str) -> bool:
        n = self.nodes.get(nid)
        if not n:
            return False
        k = (n.kind or "").lower()
        if k in {"module", "layer"}:
            return True
        if k == "kc" and self.children_by_id.get(nid):  # kc used as section header
            return True
        return False

    def container_of(self, nid: str) -> Optional[str]:
        """
        Return nearest container ancestor for this node.
        """
        cur = nid
        while True:
            p = self.parent_by_id.get(cur)
            if not p:
                return None
            if self._is_container(p):
                return p
            cur = p

    def container_groups_for_radar(self) -> Dict[str, List[str]]:
        """
        Returns: {container_id: [kc_ids...]} in global teaching order.
        Group each teachable KC by its nearest container.
        """
        groups: Dict[str, List[str]] = {}
        for kc_id in self.ordered_kc_ids:
            if not self._is_teachable_kc(kc_id):
                continue
            cid = self.container_of(kc_id) or "ROOT"
            groups.setdefault(cid, []).append(kc_id)
        return groups

    def container_ids_in_order(self) -> List[str]:
        """
        Containers ordered by first KC appearance in the teaching order.
        """
        groups = self.container_groups_for_radar()
        seen = set()
        ordered = []
        for kc_id in self.ordered_kc_ids:
            if not self._is_teachable_kc(kc_id):
                continue
            cid = self.container_of(kc_id) or "ROOT"
            if cid not in seen:
                seen.add(cid)
                ordered.append(cid)
        # keep only those that exist in groups
        return [cid for cid in ordered if cid in groups]



def normalize_adaptive_practice_pack(
    pack: Any,
    min_q: int,
    max_q: int,
) -> Tuple[int, List[dict]]:
    """
    Ensures:
    - n is clamped to [min_q, max_q]
    - questions is list[dict]
    - len(questions) controls n when the model intentionally returns fewer
    - numbers are rewritten 1..n
    """
    if not isinstance(pack, dict):
        return min_q, []

    n = pack.get("n_questions", min_q)
    try:
        n = int(n)
    except Exception:
        n = min_q

    n = max(min_q, min(n, max_q))

    questions = pack.get("questions", [])
    if not isinstance(questions, list):
        questions = []

    # truncate
    if len(questions) > n:
        questions = questions[:n]

    # If the model returned fewer questions, accept that adaptive length.
    if len(questions) < n:
        n = len(questions)

    # renumber
    for i, q in enumerate(questions, start=1):
        if isinstance(q, dict):
            q["number"] = i

    return n, questions


def estimate_practice_bounds(
    micro_lesson_text: str,
    mistakes_summary: str,
    base_min: int,
    base_max: int,
    review_kc_count: int = 0,
    attempts: int = 0,
    difficulty: str = "easy",
) -> Tuple[int, int, int]:
    """
    Estimate quiz length from lesson coverage.
    The practice should cover the lesson's essential information, not default to 3 items.
    """
    lines = [line.strip() for line in (micro_lesson_text or "").splitlines()]
    essential_count = 0
    in_essentials = False
    for line in lines:
        low = line.lower()
        if low.startswith("essential information"):
            in_essentials = True
            continue
        if in_essentials and line.startswith("-"):
            essential_count += 1
            continue
        if in_essentials and line and not line.startswith("-"):
            in_essentials = False

    if essential_count <= 0:
        essential_count = max(1, sum(1 for line in lines if line.startswith("-")))

    mistake_count = len(re.findall(r"\bQ\d+:", mistakes_summary or ""))
    integration_q = min(2, max(0, review_kc_count))
    remediation_q = min(4, mistake_count)
    difficulty_q = 2 if difficulty == "hard" else (1 if difficulty == "medium" else 0)
    retry_q = min(2, max(0, attempts - 1))

    target = essential_count + integration_q + remediation_q + difficulty_q + retry_q
    min_q = max(base_min, min(base_max, target))

    # Leave room for the model to adapt upward when the KC is dense, but avoid padding.
    spread = 1
    if essential_count >= 5:
        spread += 1
    if mistake_count >= 2:
        spread += 1
    if review_kc_count:
        spread += 1
    max_q = max(min_q, min(base_max, min_q + spread))
    return min_q, max_q, essential_count


def extract_lesson_essentials(micro_lesson_text: str) -> List[str]:
    """Extract the displayed Essential information bullets from a lesson."""
    lines = [line.strip() for line in (micro_lesson_text or "").splitlines()]
    essentials: List[str] = []
    in_essentials = False
    for line in lines:
        low = line.lower()
        if low.startswith("essential information"):
            in_essentials = True
            continue
        if in_essentials and line.startswith("-"):
            essentials.append(line[1:].strip())
            continue
        if in_essentials and line and not line.startswith("-"):
            break
    return [item for item in essentials if item]


def merge_essential_targets(kc_targets: List[str], lesson_targets: List[str], limit: int) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for target in [*kc_targets, *lesson_targets]:
        clean = re.sub(r"\s+", " ", str(target or "")).strip()
        key = clean.lower()
        if not clean or key in seen:
            continue
        seen.add(key)
        merged.append(clean)
        if len(merged) >= limit:
            break
    return merged


def estimate_practice_bounds_from_targets(
    essential_targets: List[str],
    mistakes_summary: str,
    base_min: int,
    base_max: int,
    review_kc_count: int = 0,
    attempts: int = 0,
    difficulty: str = "easy",
) -> Tuple[int, int]:
    target_count = max(1, len(essential_targets))
    mistake_count = len(re.findall(r"\bQ\d+:", mistakes_summary or ""))
    integration_q = min(2, max(0, review_kc_count))
    remediation_q = min(3, mistake_count)
    retry_q = min(2, max(0, attempts - 1))
    difficulty_q = 2 if difficulty == "hard" else (1 if difficulty == "medium" else 0)

    min_q = target_count + integration_q + remediation_q + retry_q + difficulty_q
    min_q = max(base_min, min(base_max, min_q))

    spread = 1
    if target_count >= 5:
        spread += 1
    if review_kc_count:
        spread += 1
    if mistake_count:
        spread += 1

    max_q = max(min_q, min(base_max, min_q + spread))
    return min_q, max_q


def missing_coverage_target_ids(essential_targets: List[str], coverage_plan: Any) -> List[str]:
    expected_ids = {f"E{i}" for i in range(1, len(essential_targets) + 1)}
    if not expected_ids:
        return []
    if not isinstance(coverage_plan, list):
        return sorted(expected_ids)

    covered: set[str] = set()
    for item in coverage_plan:
        if not isinstance(item, dict):
            continue
        target_id = str(item.get("target_id") or "")
        question_numbers = item.get("question_numbers") or []
        if target_id in expected_ids and isinstance(question_numbers, list) and question_numbers:
            covered.add(target_id)
    return sorted(expected_ids - covered)


def _slug(text: str, max_len: int = 40) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", (text or "").lower()).strip("_")
    return (cleaned or "unknown")[:max_len].strip("_")


def diagnostic_screening_mastery(raw_score: float) -> float:
    """
    Diagnostic QCM is screening evidence only.
    A correct single diagnostic item should not imply full KC mastery.
    """
    bounded = max(0.0, min(1.0, raw_score))
    span = DIAGNOSTIC_MAX_MASTERY - DIAGNOSTIC_MIN_MASTERY
    return DIAGNOSTIC_MIN_MASTERY + (bounded * span)


@dataclass
class MisconceptionObservation:
    kc_id: str
    label: str
    description: str
    question_number: int
    learner_letter: str
    correct_letter: str
    learner_choice: str = ""
    correct_choice: str = ""


class MisconceptionTracker:
    """Creates stable misconception labels from wrong QCM choices."""

    def detect(self, kc: KCNode, wrong_items: List[dict]) -> List[MisconceptionObservation]:
        observations: List[MisconceptionObservation] = []
        for item in wrong_items:
            learner_choice = str(item.get("learner_choice") or "").strip()
            correct_choice = str(item.get("correct_choice") or "").strip()
            learner_letter = str(item.get("learner_letter") or "?").upper()
            correct_letter = str(item.get("correct_letter") or "?").upper()

            if learner_choice and correct_choice:
                label = f"confuses_{_slug(learner_choice, 22)}_with_{_slug(correct_choice, 22)}"
                description = (
                    f"Selected {learner_letter} ({learner_choice}) instead of "
                    f"{correct_letter} ({correct_choice})."
                )
            else:
                label = f"incorrect_application_{_slug(kc.title, 28)}"
                description = (
                    f"Selected {learner_letter} instead of {correct_letter} "
                    f"for KC '{kc.title}'."
                )

            observations.append(
                MisconceptionObservation(
                    kc_id=kc.id,
                    label=label,
                    description=description,
                    question_number=int(item.get("number") or 0),
                    learner_letter=learner_letter,
                    correct_letter=correct_letter,
                    learner_choice=learner_choice,
                    correct_choice=correct_choice,
                )
            )
        return observations


@dataclass
class TutorDecision:
    action: str
    difficulty: str = "medium"
    reason: str = ""


class TutorDecisionPolicy:
    """Pedagogical policy for the ITS loop."""

    def select_difficulty(self, mastery: float, attempts: int = 0) -> str:
        if attempts <= 0 or mastery < 0.4:
            return "easy"
        if mastery < THRESHOLD:
            return "medium"
        return "hard"

    def practice_result(
        self,
        score: float,
        mastery: float,
        attempts: int,
        misconceptions: List[MisconceptionObservation],
    ) -> TutorDecision:
        if score >= THRESHOLD:
            return TutorDecision(
                action="validate_kc",
                difficulty=self.select_difficulty(mastery, attempts),
                reason="Practice score reached the KC mastery threshold.",
            )
        if misconceptions:
            return TutorDecision(
                action="hint_ladder_then_remediate",
                difficulty=self.select_difficulty(mastery, attempts),
                reason="Practice score is below threshold and misconceptions were detected.",
            )
        return TutorDecision(
            action="retry_with_micro_lesson",
            difficulty=self.select_difficulty(mastery, attempts),
            reason="Practice score is below threshold.",
        )

    def module_result(self, score: float) -> TutorDecision:
        if score >= MODULE_THRESHOLD:
            return TutorDecision(
                action="validate_module",
                difficulty="mixed",
                reason="Module checkpoint score reached the validation threshold.",
            )
        return TutorDecision(
            action="retry_module_checkpoint",
            difficulty="mixed",
            reason="Module checkpoint score is below the validation threshold.",
        )

# =====================================================
# WORKFLOW AGENTS (exactly your diagram)
# =====================================================

class DiagnosticQcmAgent:
    """Global Diagnostic QCM (across several KCs)."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=6, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Diagnostic-QCM_Agent",
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "You create a GLOBAL diagnostic multiple-choice quiz.\n"
                "Use ONLY doctrine content from file_search.\n"
                "Return ONLY valid JSON.\n"
                "Each question MUST include:\n"
                "- number (int)\n"
                "- text (string)\n"
                "- choices (array of 4 strings)\n"
                "- question text under 240 characters\n"
                "- each choice under 90 characters\n"
                "- answer (A/B/C/D)\n"
                "- kc_id (string)\n"
                "Questions must be mapped to the provided kc list."
            ),
            model_settings=ModelSettings(store=True),
        )

    async def generate(self, kc_list: List[KCNode], n_questions: int, ctx: AgentContext) -> List[dict]:
        # choose subset of KCs to cover
        # keep prompt small: send (id,title) pairs
        kcs_payload = [{"id": k.id, "title": k.title} for k in kc_list]

        prompt = f"""
Create {n_questions} diagnostic MCQ questions that cover multiple KCs.
Pick KCs from this list (use their ids):

{kcs_payload}

Rules:
- Use file_search to ground the questions.
- Each question references exactly one kc_id from the list.
- choices must be 4 short options.
- Keep question text under 240 characters.
- Keep each choice under 90 characters; avoid sentence-length choices.
- answer is one of A/B/C/D.

Return ONLY JSON list:
[
  {{"number":1,"text":"...","choices":["..","..","..",".."],"answer":"B","kc_id":"KC_xxx"}},
  ...
]
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
        raw = (res.final_output or "").strip()
        return json.loads(raw)


class KcEssentialTargetAgent:
    """Extracts essential assessable targets for a KC from the PDF."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="KC-essential-target_Agent",
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "You extract essential assessable learning targets for one KC.\n"
                "Use only PDF/course doctrine from file_search.\n"
                "Return only valid JSON.\n"
                "Targets must be specific enough to generate QCM questions.\n"
                "Do not include broad labels like 'understand the lesson'."
            ),
            model_settings=ModelSettings(store=True),
        )

    async def extract(self, kc: KCNode, micro_lesson_text: str, ctx: AgentContext) -> List[str]:
        prompt = f"""
Extract the essential assessable targets for this KC from the PDF/course.

KC:
{{"id":"{kc.id}","title":"{kc.title}","pages":{kc.pages}}}

Current micro-lesson shown to learner:
{micro_lesson_text}

Rules:
- Use file_search to retrieve the KC doctrine.
- Include every essential rule/fact needed to validate this KC.
- Each target must be testable by at least one MCQ.
- Keep targets concise.
- Prefer 3-8 targets depending on KC complexity.
- Do not create duplicate targets.
- If the KC contains a table of correspondences, include each important row as a target.

Return ONLY JSON:
{{"essential_targets":["...", "..."]}}
"""
        try:
            res = await Runner.run(self.agent, prompt, context=ctx)
            raw = (res.final_output or "").strip()
            data = json.loads(raw)
        except Exception:
            return []
        if not isinstance(data, dict) or not isinstance(data.get("essential_targets"), list):
            return []
        out: List[str] = []
        for item in data["essential_targets"]:
            clean = re.sub(r"\s+", " ", str(item or "")).strip()
            if clean:
                out.append(clean)
        return out[:10]


class PracticeQcmAgent:
    """Adaptive practice QCM for one KC (LLM chooses number of questions)."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Practice-QCM_Agent",
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "You create an ADAPTIVE practice quiz for ONE KC.\n"
                "You MUST use doctrine content grounded in file_search.\n"
                "\n"
                "Return ONLY valid JSON with EXACTLY this shape:\n"
                "{\n"
                '  "n_questions": 6,\n'
                '  "coverage_plan": [{"target_id":"E1","target":"...","question_numbers":[1]}],\n'
                '  "questions": [\n'
                '    {"number":1,"text":"...","choices":["..","..","..",".."],"answer":"A","target_id":"E1","target":"...","integrates_kc_ids":[]},\n'
                "    ...\n"
                "  ]\n"
                "}\n"
                "\n"
                "Rules:\n"
                "- n_questions must follow the provided adaptive range.\n"
                "- Choose n_questions from lesson coverage, previous-KC integration, difficulty, attempts, and mistakes.\n"
                "- Do not default to a small fixed quiz.\n"
                "- questions length MUST equal n_questions.\n"
                "- choices are 4 short options.\n"
                "- Keep question text under 240 characters for widget readability.\n"
                "- Keep each choice under 90 characters; put context in the question, not in the choices.\n"
                "- answer is one of A/B/C/D.\n"
                "- Focus on weak sub-points revealed by mistakes.\n"
            ),
            model_settings=ModelSettings(store=True),
        )

    async def generate_adaptive(
        self,
        kc: KCNode,
        review_kcs: List[KCNode],
        micro_lesson_text: str,
        mistakes_summary: str,
        difficulty: str,
        min_questions: int,
        max_questions: int,
        essential_count: int,
        essential_targets: List[str],
        ctx: AgentContext,
    ) -> Dict[str, Any]:
        review_payload = [{"id": item.id, "title": item.title} for item in review_kcs]
        targets_payload = [
            {"target_id": f"E{i}", "target": target}
            for i, target in enumerate(essential_targets, start=1)
        ]
        prompt = f"""
Build an ADAPTIVE cumulative practice QCM.

Primary KC to validate: "{kc.title}" ({kc.id})
Previous/review KCs that may be combined with the primary KC:
{review_payload}
Target difficulty: "{difficulty}"
Required question range: {min_questions}..{max_questions}
Estimated essential lesson items to cover: {essential_count}
Required essential targets from the current lesson:
{targets_payload}

Micro-lesson the learner received:
{micro_lesson_text}

Learner mistakes summary (if any):
{mistakes_summary}

Difficulty rules:
- easy: recognition, definitions, direct identification, one concept at a time.
- medium: normal application, including simple integration with previous KCs when available.
- hard: transfer, comparison, multi-step reasoning, or plausible distractors combining current and previous KCs.
- Keep every question grounded in file_search content.

Cumulative practice strategy:
- The PRIMARY learning target is always the current KC: {kc.id}.
- Most questions must test the primary KC.
- If previous/review KCs are provided, include 1-2 integrative questions that combine the primary KC with a previous KC.
- Example strategy: if the learner studied "forme" before "couleur", practice for "couleur" should include questions where color and form must both be interpreted.
- Integrative questions should still require the learner to use the primary KC, not only the previous KC.
- Do not use previous KCs that are unrelated to the current question.

Adaptive length rules:
- Choose n_questions inside the required range: {min_questions}..{max_questions}.
- Cover every required essential target at least once when possible.
- If there are {len(targets_payload)} essential targets, generate at least one question per target unless max_questions prevents it.
- Add extra questions only for detected mistakes or repeated confusion.
- Do not pad the quiz with redundant questions.

Coverage rules:
- Every question must include target_id and target.
- target_id must be one of the required essential target_ids, or "M1", "M2", ... for mistake-specific questions.
- coverage_plan must list each required essential target and which question number(s) test it.
- If an essential target cannot be tested, include it in coverage_plan with an empty question_numbers list and explain why in "coverage_note".
- Do not validate the KC with questions that test only previous/review KCs.
- Keep question text under 240 characters.
- Keep each choice under 90 characters; avoid sentence-length choices.

Return ONLY JSON:
{{
  "n_questions": <int {min_questions}..{max_questions}>,
  "coverage_plan": [
    {{"target_id":"E1","target":"...","question_numbers":[1],"coverage_note":""}}
  ],
  "questions": [
    {{"number":1,"text":"...","choices":["..","..","..",".."],"answer":"B","target_id":"E1","target":"essential item, mistake, or integration tested","integrates_kc_ids":["..."]}},
    ...
  ]
}}
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
        raw = (res.final_output or "").strip()
        return json.loads(raw)

    async def repair_coverage(
        self,
        kc: KCNode,
        review_kcs: List[KCNode],
        existing_pack: Dict[str, Any],
        essential_targets: List[str],
        missing_target_ids: List[str],
        difficulty: str,
        min_questions: int,
        max_questions: int,
        ctx: AgentContext,
    ) -> Dict[str, Any]:
        targets_payload = [
            {"target_id": f"E{i}", "target": target}
            for i, target in enumerate(essential_targets, start=1)
        ]
        review_payload = [{"id": item.id, "title": item.title} for item in review_kcs]
        prompt = f"""
Repair this practice QCM before it is shown to the learner.

Primary KC: "{kc.title}" ({kc.id})
Previous/review KCs:
{review_payload}
Difficulty: {difficulty}
Required range: {min_questions}..{max_questions}
Required essential targets:
{targets_payload}
Missing target ids:
{missing_target_ids}

Existing QCM:
{existing_pack}

Repair rules:
- Return a complete replacement JSON pack.
- Keep valid existing questions when useful.
- Add or rewrite questions so every E target has at least one question.
- Each question must primarily validate the current KC.
- Integrative questions may use review KCs but must still require the current KC.
- Number of questions must be inside {min_questions}..{max_questions}.
- Use file_search for PDF grounding.
- No duplicate questions.
- Keep question text under 240 characters.
- Keep each choice under 90 characters; avoid sentence-length choices.

Return ONLY JSON with the same shape:
{{
  "n_questions": <int>,
  "coverage_plan": [
    {{"target_id":"E1","target":"...","question_numbers":[1],"coverage_note":""}}
  ],
  "questions": [
    {{"number":1,"text":"...","choices":["..","..","..",".."],"answer":"B","target_id":"E1","target":"...","integrates_kc_ids":[]}}
  ]
}}
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
        raw = (res.final_output or "").strip()
        return json.loads(raw)


class ModuleQcmAgent:
    """Global module checkpoint quiz (covers all KCs in one module)."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Module-QCM_Agent",
            model="gpt-5.1",
            tools=[self.tool],
            instructions=(
                "You create a MODULE checkpoint multiple-choice quiz.\n"
                "Use ONLY doctrine content from file_search.\n"
                "Return ONLY valid JSON.\n"
                "Each question MUST include:\n"
                "- number (int)\n"
                "- text (string)\n"
                "- choices (array of 4 strings)\n"
                "- question text under 240 characters\n"
                "- each choice under 90 characters\n"
                "- answer (A/B/C/D)\n"
                "- kc_id (string)\n"
                "Questions must be mapped to the provided kc list."
            ),
            model_settings=ModelSettings(store=True),
        )

    async def generate(self, module_title: str, kc_list: List[KCNode], n_questions: int, ctx: AgentContext) -> List[dict]:
        kcs_payload = [{"id": k.id, "title": k.title} for k in kc_list]
        prompt = f"""
Create {n_questions} MCQ questions as a module checkpoint quiz for module: "{module_title}".

KCs to cover (use their ids):
{kcs_payload}

Rules:
- Use file_search to ground the questions.
- Each question references exactly one kc_id from the list.
- choices must be 4 short options.
- Keep question text under 240 characters.
- Keep each choice under 90 characters; avoid sentence-length choices.
- answer is one of A/B/C/D.

Return ONLY JSON list:
[
  {{"number":1,"text":"...","choices":["..","..","..",".."],"answer":"B","kc_id":"KC_xxx"}},
  ...
]
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
        raw = (res.final_output or "").strip()
        return json.loads(raw)



class MicroLessonAgent:
    """Adaptive KC micro-lesson rendered from a required lesson form."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Micro-lesson_Agent",
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "You create an adaptive micro-lesson ONLY about the provided KC.\n"
                "Ground every field in doctrine using file_search.\n"
                "Return ONLY valid JSON, no markdown code fences.\n"
                "The lesson must be short but must not omit essential doctrine for the KC.\n"
                "Return this exact shape:\n"
                "{\n"
                '  "lesson_plan": {\n'
                '    "lesson_complexity": "simple|medium|complex",\n'
                '    "lesson_mode": "first_exposure|remediation|focused_review|brief_validation",\n'
                '    "max_words": 240,\n'
                '    "essential_information_count": 4,\n'
                '    "reason": "..."\n'
                "  },\n"
                '  "lesson": {\n'
                '    "title": "...",\n'
                '    "source_basis": ["short copied or tightly paraphrased doctrine point from the PDF", "..."],\n'
                '    "learning_objective": "...",\n'
                '    "essential_information": ["...", "..."],\n'
                '    "rule_to_remember": "...",\n'
                '    "operational_example": "...",\n'
                '    "common_mistake": "...",\n'
                '    "targeted_remediation": "...",\n'
                '    "self_check": "..."\n'
                "  }\n"
                "}\n"
                "Rules:\n"
                "- First retrieve the PDF content for the KC with file_search.\n"
                "- lesson_plan must choose a budget from the KC complexity and learner state.\n"
                "- max_words must be as short as possible but complete enough for the KC.\n"
                "- source_basis must contain the key PDF facts/terms used to build the lesson.\n"
                "- Preserve official doctrine terms, labels, colors, symbols, and operational names exactly when they appear in the PDF.\n"
                "- Reformulate only explanations, not official terms.\n"
                "- Do not add external knowledge or invented rules.\n"
                "- If the PDF evidence is insufficient, say that in source_basis and keep the lesson conservative.\n"
            ),
            model_settings=ModelSettings(store=True),
        )

    def _validate_lesson_plan(
        self,
        plan: Any,
        fallback_mode: str,
        fallback_essential_count: str,
    ) -> Dict[str, Any]:
        if not isinstance(plan, dict):
            plan = {}

        complexity = str(plan.get("lesson_complexity") or "medium").lower().strip()
        if complexity not in {"simple", "medium", "complex"}:
            complexity = "medium"

        mode = str(plan.get("lesson_mode") or fallback_mode).lower().strip()
        if mode not in {"first_exposure", "remediation", "focused_review", "brief_validation"}:
            mode = fallback_mode

        try:
            requested_words = int(plan.get("max_words") or 0)
        except Exception:
            requested_words = 0

        budget_by_mode_complexity = {
            "brief_validation": {"simple": 90, "medium": 110, "complex": 130},
            "focused_review": {"simple": 140, "medium": 180, "complex": 220},
            "remediation": {"simple": 160, "medium": 220, "complex": 280},
            "first_exposure": {"simple": 180, "medium": 260, "complex": 360},
        }
        max_allowed = budget_by_mode_complexity[mode][complexity]
        min_allowed = 80 if mode != "brief_validation" else 50
        if requested_words <= 0:
            requested_words = max_allowed
        max_words = max(min_allowed, min(requested_words, max_allowed))

        try:
            essential_count = int(plan.get("essential_information_count") or 0)
        except Exception:
            essential_count = 0
        if essential_count <= 0:
            m = re.search(r"\d+", fallback_essential_count)
            essential_count = int(m.group(0)) if m else 3
        essential_count = max(1, min(essential_count, 7))

        return {
            "lesson_complexity": complexity,
            "lesson_mode": mode,
            "max_words": max_words,
            "essential_information_count": essential_count,
            "reason": str(plan.get("reason") or "").strip(),
            "max_allowed_words": max_allowed,
        }

    def _format_lesson_form(self, data: Dict[str, Any], fallback_title: str) -> str:
        title = str(data.get("title") or fallback_title).strip()
        source_basis = data.get("source_basis") or []
        if not isinstance(source_basis, list):
            source_basis = [str(source_basis)]
        source_basis = [str(x).strip() for x in source_basis if str(x).strip()]
        objective = str(data.get("learning_objective") or "").strip()
        essentials = data.get("essential_information") or []
        if not isinstance(essentials, list):
            essentials = [str(essentials)]
        essentials = [str(x).strip() for x in essentials if str(x).strip()]
        rule = str(data.get("rule_to_remember") or "").strip()
        example = str(data.get("operational_example") or "").strip()
        mistake = str(data.get("common_mistake") or "").strip()
        remediation = str(data.get("targeted_remediation") or "").strip()
        self_check = str(data.get("self_check") or "").strip()

        lines = [title]
        if source_basis:
            lines.append("PDF basis:")
            lines.extend(f"- {item}" for item in source_basis[:4])
        if objective:
            lines.append(f"Objective: {objective}")
        if essentials:
            lines.append("Essential information:")
            lines.extend(f"- {item}" for item in essentials[:5])
        if rule:
            lines.append(f"Rule to remember: {rule}")
        if example:
            lines.append(f"Example: {example}")
        if mistake:
            lines.append(f"Common mistake: {mistake}")
        if remediation:
            lines.append(f"Targeted remediation: {remediation}")
        if self_check:
            lines.append(f"Self-check: {self_check}")
        return "\n".join(lines)

    async def build(
        self,
        kc: KCNode,
        ctx: AgentContext,
        mastery: float = 0.0,
        attempts: int = 0,
        mistakes_summary: str = "",
        misconception_labels: Optional[List[str]] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        misconception_labels = misconception_labels or []
        if attempts <= 0:
            lesson_mode = "first_exposure"
            essential_count = "3-5"
            focus = "Give the minimum foundation needed before first practice."
        elif mastery < 0.4 or misconception_labels:
            lesson_mode = "remediation"
            essential_count = "2-4"
            focus = "Target the specific mistake pattern. Do not reteach the whole KC."
        elif mastery < THRESHOLD:
            lesson_mode = "focused_review"
            essential_count = "2-3"
            focus = "Review only the weak point needed for the next practice."
        else:
            lesson_mode = "brief_validation"
            essential_count = "1-2"
            focus = "Give a very short confirmation and one transfer tip."

        prompt = f"""
Teach the learner a micro-lesson on this KC only.

KC title: "{kc.title}"
KC id: "{kc.id}"
Learner level estimate for this KC: {mastery:.2f}
This estimate may come from diagnostic screening and must not be treated as KC validation.
Practice attempts on this KC: {attempts}
Lesson mode: {lesson_mode}
Detected misconception labels:
{misconception_labels}

Recent mistake summary:
{mistakes_summary or "(No mistakes yet.)"}

Constraints:
- {focus}
- Fill every field in the lesson form.
- The lesson must be built from PDF content retrieved with file_search, not from general memory.
- lesson_plan.lesson_mode should usually be "{lesson_mode}" unless the PDF evidence clearly justifies another mode.
- lesson_plan.essential_information_count should match the number of essential PDF points needed for this KC.
- source_basis must list the PDF facts/terms that justify the lesson.
- essential_information must contain {essential_count} concise items.
- Keep each field concise, but include all essential doctrine needed for this KC.
- If the KC has several essential rules, include them as separate essential_information items.
- Keep official PDF terms exactly; reformulate around them only to improve learner understanding.
- Do not invent examples that contradict or go beyond the PDF doctrine.
- If misconceptions are provided, explain exactly that confusion.
- If no misconceptions are provided, teach only the core rule for first practice.
- Use file_search to ground definitions/rules.
- Return ONLY valid JSON with the required schema.
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
        raw = (res.final_output or "").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw, {
                "lesson_complexity": "unknown",
                "lesson_mode": lesson_mode,
                "max_words": 220,
                "essential_information_count": 0,
                "reason": "Model returned non-JSON lesson text.",
                "max_allowed_words": 220,
            }
        if not isinstance(data, dict):
            return raw, {
                "lesson_complexity": "unknown",
                "lesson_mode": lesson_mode,
                "max_words": 220,
                "essential_information_count": 0,
                "reason": "Model returned JSON that was not an object.",
                "max_allowed_words": 220,
            }
        plan = self._validate_lesson_plan(
            data.get("lesson_plan"),
            fallback_mode=lesson_mode,
            fallback_essential_count=essential_count,
        )
        lesson_data = data.get("lesson") if isinstance(data.get("lesson"), dict) else data
        return self._format_lesson_form(lesson_data, kc.title), plan




class ExplainMistakeAgent:
    """Explain mistakes when score below threshold."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Explain-mistake_Agent",
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "Tu expliques les erreurs de l'apprenant brievement et clairement.\n"
                "Reponds toujours en francais.\n"
                "Use doctrine from file_search.\n"
                "Output plain text (no JSON).\n"
                "Do not expose internal misconception labels.\n"
                "Do not list every error if there are many; group similar errors.\n"
                "Include: score interpretation, 2-4 key corrections, one mini-remediation, and next action."
            ),
            model_settings=ModelSettings(store=True),
        )

    async def explain(self, kc: KCNode, wrong_items: List[dict], ctx: AgentContext) -> str:
        limited_wrong_items = wrong_items[:5]
        prompt = f"""
L'apprenant n'a pas encore valide cette KC: "{kc.title}" ({kc.id})

Erreurs observees, limitees aux plus importantes:
{limited_wrong_items}

Explique les erreurs avec la doctrine du PDF.
Contraintes:
- Reponds en francais.
- Maximum 140 mots.
- Ne montre jamais les labels internes comme "confuses_...".
- Regroupe les erreurs similaires.
- Donne une mini-remediation concrete.
- Termine par: Tape "hint" pour un indice ou "practice" pour refaire un QCM cible.
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
        return (res.final_output or "").strip()


class LearnerQuestionAgent:
    """Answers learner questions only inside the current learning frontier."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Learner-question_Agent",
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "You answer learner clarification questions during a micro-lesson.\n"
                "Use file_search for PDF grounding.\n"
                "You may answer ONLY if the question concerns the current KC or previous KCs provided by the orchestrator.\n"
                "If the learner asks about a future KC, do not teach it. Say it will be covered later and redirect to the current KC.\n"
                "If the question is outside the course/PDF, say it is outside the current lesson scope.\n"
                "Keep answers concise, pedagogical, and grounded in the provided allowed KC list.\n"
                "Return plain text only."
            ),
            model_settings=ModelSettings(store=True),
        )

    async def answer(
        self,
        question: str,
        current_kc: KCNode,
        allowed_kcs: List[KCNode],
        future_kcs: List[KCNode],
        current_micro_lesson: str,
        ctx: AgentContext,
    ) -> str:
        allowed_payload = [
            {"id": kc.id, "title": kc.title, "pages": kc.pages}
            for kc in allowed_kcs
        ]
        future_payload = [
            {"id": kc.id, "title": kc.title}
            for kc in future_kcs[:12]
        ]
        prompt = f"""
Learner question:
{question}

Current KC:
{{"id":"{current_kc.id}","title":"{current_kc.title}","pages":{current_kc.pages}}}

Allowed KCs for answering (current + previous only):
{allowed_payload}

Future KCs that must NOT be taught yet:
{future_payload}

Current micro-lesson text:
{current_micro_lesson or "(No current micro-lesson text stored.)"}

Decision rules:
- If the question is answerable using the current KC or allowed previous KCs, answer it with PDF-grounded explanation.
- If it requires a future KC, briefly say it is not part of the current learning step yet, name the current KC, and offer a small bridge without teaching the future KC.
- If it is outside the PDF/course, say it is outside the current lesson scope.
- Do not reveal full future-KC content, definitions, examples, or rules.
- Mention source pages when available.
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
        return (res.final_output or "").strip()


class VisualQuestionAgent:
    """Answers learner questions about uploaded symbol images using the whole PDF course."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Visual-symbol-question_Agent",
            model="gpt-5.5",
            tools=[self.tool],
            instructions=(
                "Tu es un tuteur visuel pour les symboles cartographiques.\n"
                "Reponds toujours en francais, sauf si l'apprenant demande une autre langue.\n"
                "Analyse tous les elements visibles de l'image en details "
            ),
            model_settings=ModelSettings(store=True),
        )

    async def answer(
        self,
        question: str,
        image_urls: List[str],
        current_kc: Optional[KCNode],
        course_kcs: List[KCNode],
        current_micro_lesson: str,
        visual_context: List[dict],
        ctx: AgentContext,
    ) -> str:
        course_payload = [
            {"id": kc.id, "title": kc.title, "pages": kc.pages}
            for kc in course_kcs
        ]
        current_payload = (
            {"id": current_kc.id, "title": current_kc.title, "pages": current_kc.pages}
            if current_kc
            else None
        )
        prompt = f"""
L'apprenant a ajoute une ou plusieurs images de symbole et demande :
{question or "Que signifie ce symbole ?"}

KC actuelle, si l'apprenant est dans une lecon :
{current_payload or "(Aucune KC actuelle. Repondre avec tout le PDF du cours.)"}

KCs/pages disponibles dans le cours :
{course_payload}

Micro-lecon actuelle :
{current_micro_lesson or "(Aucune micro-lecon memorisee.)"}

Historique recent sur la meme image :
{visual_context[-6:] if visual_context else "(Aucun historique visuel.)"}

Regles :
- Decris d'abord ce que tu vois : forme, couleur, contour, texte ou pictogramme.
- Si la question est une relance courte ("et la couleur ?", "pourquoi ?", "et la forme ?"), utilise l'historique recent et la meme image.
- Relie chaque element visible a la signification exacte dans le PDF.
- Ne dis pas "consultez le tableau" si la reponse est dans le PDF.
- Exemple de precision attendue : "triangle = avertissement / danger / actions SP".
- Si plusieurs elements sont utiles, donne une interpretation combinee.
- Cite les pages sources quand elles sont disponibles.

Format de reponse :
1. "Je vois..."
2. "Signification..."
3. "Interpretation..."
4. "Source..."
"""
        content: List[dict] = [{"type": "input_text", "text": prompt}]
        for image_url in image_urls:
            content.append({"type": "input_image", "image_url": image_url, "detail": "auto"})
        res = await Runner.run(
            self.agent,
            [{"role": "user", "content": content}],
            context=ctx,
        )
        return (res.final_output or "").strip()


class ScoreFindWeaknessAgent:
    """Score + Find weakness (pure python)."""

    def find_weakness(
        self,
        question_to_kc: Dict[int, str],
        user_answers: Dict[int, str],
        correct_answers: Dict[int, str],
    ) -> Tuple[Optional[str], float, Dict[str, Tuple[int, int]]]:
        """
        Returns:
        - weakness_kc_id
        - overall_score (0..1)
        - per_kc_stats: kc_id -> (correct_count, total_count)
        """
        total = len(correct_answers) or 1
        correct_total = 0

        per: Dict[str, Tuple[int, int]] = {}

        for qnum, correct in correct_answers.items():
            kc_id = question_to_kc.get(qnum)
            if not kc_id:
                continue
            u = user_answers.get(qnum, "").upper()
            is_ok = (u == correct.upper())
            correct_total += 1 if is_ok else 0

            c_cnt, t_cnt = per.get(kc_id, (0, 0))
            per[kc_id] = (c_cnt + (1 if is_ok else 0), t_cnt + 1)

        overall = correct_total / total

        weakness = None
        weakness_score = 2.0
        for kc_id, (c_cnt, t_cnt) in per.items():
            s = (c_cnt / t_cnt) if t_cnt else 1.0
            if s < weakness_score:
                weakness_score = s
                weakness = kc_id

        return weakness, overall, per


# =====================================================
# EVALUATOR (kept for compatibility with your server)
# =====================================================
class EvaluatorAgent:
    def evaluate(self, user: Dict[int, str], correct: Dict[int, str]):
        score = 0
        details: List[str] = []
        for num, ans in correct.items():
            user_ans = user.get(num, "").upper()
            if user_ans == ans:
                score += 1
                details.append(f"Q{num}: ✓ Correct ({user_ans})")
            else:
                details.append(f"Q{num}: ✗ Wrong (Your: {user_ans}, Correct: {ans})")
        score20 = round((score / max(1, len(correct))) * 20, 2)
        return score, score20, details


# =====================================================
# SESSION STATE (per thread)
# =====================================================
@dataclass
class Session:
    phase: str = "idle"
    scope: str = "diagnostic"
    current_kc_id: Optional[str] = None

    last_hidden_answers: Dict[int, str] = field(default_factory=dict)
    last_question_to_kc: Dict[int, str] = field(default_factory=dict)
    last_question_text: Dict[int, dict] = field(default_factory=dict)

    mastery: Dict[str, float] = field(default_factory=dict)
    last_score_by_kc: Dict[str, float] = field(default_factory=dict)
    diagnostic_profile: Dict[str, float] = field(default_factory=dict)
    diagnostic_raw_score_by_kc: Dict[str, float] = field(default_factory=dict)
    kc_essential_targets: Dict[str, List[str]] = field(default_factory=dict)

    # ✅ Option B memory
    current_micro_lesson: str = ""          # last generated micro-lesson for current KC
    last_mistakes_summary: str = ""         # compact summary used to adapt practice
    misconceptions: Dict[str, List[str]] = field(default_factory=dict)
    misconception_evidence: Dict[str, List[dict]] = field(default_factory=dict)
    attempts_by_kc: Dict[str, int] = field(default_factory=dict)
    pending_hint_ladder: List[str] = field(default_factory=list)
    hint_index: int = 0
    evidence_events: List[dict] = field(default_factory=list)
    last_tutor_action: str = ""
    
    # ✅ NEW: gate for "next"
    can_advance: bool = False
    validated_kc_id: Optional[str] = None
    pending_next_kc_id: Optional[str] = None

    current_module_id: Optional[str] = None

    pending_module_id: Optional[str] = None     # module that must be validated by checkpoint
    module_gate_locked: bool = False            # True => must pass module quiz before next


    module_mastery: Dict[str, float] = field(default_factory=dict)
    pending_module_retry: bool = False
    last_module_feedback: str = ""
    last_visual_image_urls: List[str] = field(default_factory=list)
    visual_question_history: List[dict] = field(default_factory=list)

# =====================================================
# ORCHESTRATOR (workflow)
# =====================================================
class Orchestrator:
    """
    Implements:
    A[System runs Global Diagnostic QCM] --> B[Diagnostic-QCM_Agent]
    B --> C[Score + Find-Weakness_Agent]
    C --> D[Micro-lesson_Agent]
    D --> E[Practice-QCM_Agent]
    E --> F{Score < threshold?}
    F -- YES --> G[Explain-mistake_Agent]
    G --> D
    F -- NO --> H[Validated -> Next KC/Module or Stop]
    """

    def __init__(self):
        # load KC graph once
        self.graph = KcGraph.load(KC_GRAPH_PATH)

        # workflow agents
        self.diagnostic_qcm = DiagnosticQcmAgent()
        self.kc_targets = KcEssentialTargetAgent()
        self.scorer = ScoreFindWeaknessAgent()
        self.micro_lesson = MicroLessonAgent()
        self.practice_qcm = PracticeQcmAgent()
        self.explain_mistake = ExplainMistakeAgent()
        self.learner_question = LearnerQuestionAgent()
        self.visual_question = VisualQuestionAgent()
        self.module_qcm = ModuleQcmAgent()
        self.policy = TutorDecisionPolicy()
        self.misconception_tracker = MisconceptionTracker()
        # compatibility with your server
        self.evaluator = EvaluatorAgent()
        self.hidden_answers: Dict[int, str] | None = None  # <-- server reads this in qcm.submit

        # sessions per thread
        self._sessions: Dict[str, Session] = {}

    # --------------------------
    # Compatibility method used in your server
    # --------------------------
    def format_evaluation(self, score, score20, details):
        return f"""📊 Evaluation

Score: {score}/{len(details)}
Score /20: {score20}

Details:
{chr(10).join(details)}
"""

    # --------------------------
    def _get_sess(self, ctx: AgentContext) -> Session:
        tid = getattr(ctx.thread, "id", "default-thread")
        if tid not in self._sessions:
            self._sessions[tid] = Session()
        return self._sessions[tid]

    def _kc_nodes_for_diagnostic(self) -> List[KCNode]:
        # pick up to 8 KCs from the graph (can be improved later)
        ids = self.graph.kc_ids()
        picked = ids[: min(len(ids), 8)]
        return [self.graph.nodes[i] for i in picked if i in self.graph.nodes]

    def _kc_ref_pages(self, kc: KCNode) -> List[int]:
        pages = [p for p in kc.pages if isinstance(p, int) and p > 0]
        return sorted(set(pages))

    def _build_lesson_with_refs(self, kc: KCNode, lesson_text: str) -> Dict[str, Any]:
        pages = self._kc_ref_pages(kc)
        if not pages:
            return {"type": "lesson_with_ref", "text": lesson_text}

        refs_txt = ", ".join(f"p.{p}" for p in pages)
        full_text = f"{lesson_text}\n\nReferences: {refs_txt}"

        first_page = pages[0]
        pdf_name = self.graph.source_pdf or "Charte graphique 2025 - Impression.pdf"
        pdf_url = f"{PUBLIC_BASE_URL}/static/{quote(pdf_name)}#page={first_page}"
        html = ""

        return {
            "type": "lesson_with_ref",
            "text": full_text,
            "ref_widget": {
                "title": f"Source - {kc.title}",
                "subtitle": f"Reference: p.{first_page}",
                "buttonLabel": f"Open source p.{first_page}",
                "icon": "analytics",
                "url": pdf_url,
                "html": html,
            },
        }

    def _thread_id(self, ctx: AgentContext) -> str:
        return str(getattr(ctx.thread, "id", "default-thread"))

    def _record_event(self, sess: Session, ctx: AgentContext, event: Dict[str, Any]) -> None:
        enriched = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "thread_id": self._thread_id(ctx),
            **event,
        }
        sess.evidence_events.append(enriched)
        try:
            os.makedirs(os.path.dirname(EVIDENCE_LOG_PATH), exist_ok=True)
            with open(EVIDENCE_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(enriched, ensure_ascii=False, default=str) + "\n")
        except Exception as exc:
            print(f"Evidence logging failed: {exc}")

    def _choice_text(self, qinfo: dict, letter: str) -> str:
        choices = qinfo.get("choices", [])
        idx = ord(str(letter or "").upper()[:1] or "A") - ord("A")
        if isinstance(choices, list) and 0 <= idx < len(choices):
            return str(choices[idx])
        return ""

    def _build_wrong_items(self, sess: Session, answers: Dict[int, str], correct: Dict[int, str]) -> List[dict]:
        wrong_items: List[dict] = []
        for qnum, corr in correct.items():
            learner = answers.get(qnum, "")
            if learner.upper() == corr.upper():
                continue
            qinfo = sess.last_question_text.get(qnum, {})
            wrong_items.append({
                "number": qnum,
                "question": qinfo.get("text", ""),
                "choices": qinfo.get("choices", []),
                "correct_letter": corr,
                "learner_letter": learner,
                "correct_choice": self._choice_text(qinfo, corr),
                "learner_choice": self._choice_text(qinfo, learner),
            })
        return wrong_items

    def _store_misconceptions(
        self,
        sess: Session,
        observations: List[MisconceptionObservation],
    ) -> None:
        for obs in observations:
            labels = sess.misconceptions.setdefault(obs.kc_id, [])
            if obs.label not in labels:
                labels.append(obs.label)
            sess.misconception_evidence.setdefault(obs.kc_id, []).append({
                "label": obs.label,
                "description": obs.description,
                "question_number": obs.question_number,
                "learner_letter": obs.learner_letter,
                "correct_letter": obs.correct_letter,
                "learner_choice": obs.learner_choice,
                "correct_choice": obs.correct_choice,
            })

    def _build_hint_ladder(
        self,
        kc: KCNode,
        observations: List[MisconceptionObservation],
        wrong_items: List[dict],
    ) -> List[str]:
        if observations:
            first = observations[0]
            contrast = (
                f"Compare ton idee choisie ({first.learner_choice or first.learner_letter}) "
                f"avec l'idee attendue ({first.correct_choice or first.correct_letter})."
            )
        elif wrong_items:
            contrast = "Compare l'option choisie avec la bonne option et retrouve la regle de doctrine qui les separe."
        else:
            contrast = "Identifie la regle de doctrine utilisee par cette KC avant de repondre."

        pages = self._kc_ref_pages(kc)
        page_hint = f" Revois la page source: {', '.join('p.' + str(p) for p in pages)}." if pages else ""
        return [
            f"Indice 1: Concentre-toi sur la KC '{kc.title}'.{page_hint}",
            f"Indice 2: {contrast}",
            "Indice 3: Elimine les options qui decrivent une KC voisine au lieu de la KC actuelle.",
            "Dernier guidage: reformule la regle avec tes mots, puis applique-la a la situation de la question.",
        ]

    def _next_hint_text(self, sess: Session) -> str:
        if not sess.pending_hint_ladder:
            return "Aucun indice en attente. Tape: practice"
        idx = min(sess.hint_index, len(sess.pending_hint_ladder) - 1)
        hint = sess.pending_hint_ladder[idx]
        sess.hint_index = min(idx + 1, len(sess.pending_hint_ladder))
        if sess.hint_index >= len(sess.pending_hint_ladder):
            return f"{hint}\n\nIl n'y a plus d'indices. Tape: practice"
        return f"{hint}\n\nTape: hint pour l'indice suivant, ou practice pour refaire le QCM."

    def _clear_quiz_state(self, sess: Session) -> None:
        sess.last_hidden_answers = {}
        sess.last_question_to_kc = {}
        sess.last_question_text = {}
        self.hidden_answers = None

    def _learning_frontier(self, current_kc_id: str) -> Tuple[List[KCNode], List[KCNode]]:
        ordered = self.graph.kc_ids()
        idx = self.graph.index_by_kc.get(current_kc_id)
        if idx is None:
            return [], []
        allowed_ids = ordered[: idx + 1]
        future_ids = ordered[idx + 1 :]
        allowed = [self.graph.nodes[kid] for kid in allowed_ids if kid in self.graph.nodes]
        future = [self.graph.nodes[kid] for kid in future_ids if kid in self.graph.nodes]
        return allowed, future

    async def _answer_learner_question(self, sess: Session, question: str, ctx: AgentContext) -> Any:
        if not sess.current_kc_id or sess.current_kc_id not in self.graph.nodes:
            return (
                "I can answer lesson questions after a KC is selected. "
                "Type: start diagnostic"
            )

        current_kc = self.graph.nodes[sess.current_kc_id]
        allowed_kcs, future_kcs = self._learning_frontier(current_kc.id)
        answer = await self.learner_question.answer(
            question=question,
            current_kc=current_kc,
            allowed_kcs=allowed_kcs,
            future_kcs=future_kcs,
            current_micro_lesson=sess.current_micro_lesson,
            ctx=ctx,
        )
        sess.last_tutor_action = "answer_lesson_question"
        self._record_event(sess, ctx, {
            "event": "learner_question_answered",
            "tutor_action": sess.last_tutor_action,
            "question": question,
            "current_kc_id": current_kc.id,
            "current_kc_title": current_kc.title,
            "allowed_kc_ids": [kc.id for kc in allowed_kcs],
            "future_kc_ids": [kc.id for kc in future_kcs],
            "source_pages": sorted({p for kc in allowed_kcs for p in self._kc_ref_pages(kc)}),
            "answer_preview": answer[:1000],
        })
        return answer

    async def _answer_visual_question(
        self,
        sess: Session,
        question: str,
        image_urls: List[str],
        ctx: AgentContext,
    ) -> Any:
        is_followup = False
        if image_urls:
            sess.last_visual_image_urls = list(image_urls)
            sess.visual_question_history = []
        else:
            image_urls = list(sess.last_visual_image_urls)
            is_followup = True

        if not image_urls:
            return "Ajoute d'abord une image de symbole, puis pose ta question."

        current_kc = self.graph.nodes.get(sess.current_kc_id or "")
        course_kcs = [
            self.graph.nodes[kid]
            for kid in self.graph.kc_ids()
            if kid in self.graph.nodes
        ]
        answer = await self.visual_question.answer(
            question=question,
            image_urls=image_urls,
            current_kc=current_kc,
            course_kcs=course_kcs,
            current_micro_lesson=sess.current_micro_lesson,
            visual_context=sess.visual_question_history,
            ctx=ctx,
        )
        sess.visual_question_history.append({
            "question": question or "Que signifie ce symbole ?",
            "answer": answer[:1200],
        })
        sess.visual_question_history = sess.visual_question_history[-8:]
        sess.last_tutor_action = "answer_visual_pdf_question"
        self._record_event(sess, ctx, {
            "event": "visual_question_answered",
            "tutor_action": sess.last_tutor_action,
            "question": question or "What does this symbol mean?",
            "n_images": len(image_urls),
            "image_context_reused": is_followup,
            "scope": "full_pdf_course",
            "current_kc_id": current_kc.id if current_kc else None,
            "current_kc_title": current_kc.title if current_kc else None,
            "course_kc_ids": [kc.id for kc in course_kcs],
            "source_pages": sorted({p for kc in course_kcs for p in self._kc_ref_pages(kc)}),
            "answer_preview": answer[:1000],
        })
        return answer

    async def _build_adaptive_micro_lesson(
        self,
        sess: Session,
        kc: KCNode,
        ctx: AgentContext,
        mistakes_summary: str = "",
    ) -> str:
        mastery_value = sess.mastery.get(kc.id)
        diagnostic_level = sess.diagnostic_profile.get(kc.id)
        learner_level = float(mastery_value if mastery_value is not None else (diagnostic_level or 0.0))
        attempts = int(sess.attempts_by_kc.get(kc.id, 0))
        labels = list(sess.misconceptions.get(kc.id, []))
        summary = mistakes_summary or sess.last_mistakes_summary
        lesson, lesson_plan = await self.micro_lesson.build(
            kc=kc,
            ctx=ctx,
            mastery=learner_level,
            attempts=attempts,
            mistakes_summary=summary,
            misconception_labels=labels,
        )
        self._record_event(sess, ctx, {
            "event": "micro_lesson_generated",
            "kc_id": kc.id,
            "kc_title": kc.title,
            "mastery": mastery_value,
            "diagnostic_level": diagnostic_level,
            "learner_level_for_adaptation": learner_level,
            "attempts": attempts,
            "misconceptions": labels,
            "source_pages": self._kc_ref_pages(kc),
            "word_estimate": len(lesson.split()),
            "lesson_plan": lesson_plan,
            "lesson_budget_words": lesson_plan.get("max_words"),
            "lesson_complexity": lesson_plan.get("lesson_complexity"),
            "lesson_mode": lesson_plan.get("lesson_mode"),
            "lesson_preview": lesson[:1200],
        })
        return lesson


    async def _next_kc_micro_lesson(self, sess: Session, ctx: AgentContext) -> Any:
        # must have a current KC
        if not sess.current_kc_id:
            return "⚠️ No current KC. Type: start diagnostic"

        # ✅ Gate check: only after passing practice for this KC
        if not sess.can_advance or sess.validated_kc_id != sess.current_kc_id:
            return (
                "⚠️ You can type `next` only after validating the current KC.\n"
                "Type: practice"
            )
        # ✅ New: module gate check
        if sess.module_gate_locked:
            mod_title = "Module"
            if sess.pending_module_id and sess.pending_module_id in self.graph.nodes:
                mod_title = self.graph.nodes[sess.pending_module_id].title
            return (
                f"⚠️ You must pass the module checkpoint quiz for: {mod_title}\n"
                f"Submit the module quiz (if shown), or type: practice to remediate."
            )

        nxt = sess.pending_next_kc_id or self.graph.next_kc(sess.current_kc_id)
        if not nxt or nxt not in self.graph.nodes:
            sess.can_advance = False
            sess.validated_kc_id = None
            sess.pending_next_kc_id = None
            return "🏁 No next KC. You finished the course sequence."

        sess.current_kc_id = nxt
        sess.pending_next_kc_id = None
        sess.scope = "practice"
        sess.phase = "idle"

        # reset adaptation memory
        sess.last_mistakes_summary = ""
        sess.current_micro_lesson = ""

        # ✅ Lock gate again until next KC is passed
        sess.can_advance = False
        sess.validated_kc_id = None
        sess.pending_next_kc_id = None
        
        kc = self.graph.nodes[nxt]
        lesson_text = await self._build_adaptive_micro_lesson(sess, kc, ctx)
        sess.current_micro_lesson = lesson_text

        text = (
            f"📘 Next KC: {kc.title}\n\n"
            f"{lesson_text}\n\n"
            f"➡️ Type: practice"
        )
        return self._build_lesson_with_refs(kc, text)
    
    async def _show_radar(self, sess: Session) -> dict:
        groups = self.graph.container_groups_for_radar()
        container_ids = self.graph.container_ids_in_order()

        views = {}

        # View 1: Containers radar (container score = avg KC mastery)
        labels, vals = [], []
        for cid in container_ids:
            kc_ids = groups.get(cid, [])
            if cid == "ROOT":
                title = "ROOT"
            else:
                title = self.graph.nodes[cid].title if cid in self.graph.nodes else cid

            m = [float(sess.mastery.get(k, 0.0)) for k in kc_ids]
            score = (sum(m) / max(1, len(m))) if m else 0.0

            labels.append(title)
            vals.append(score)

        views["modules"] = {"label": "Sections", "labels": labels, "values": vals}

        # View per container: its KCs
        for cid in container_ids:
            kc_ids = groups.get(cid, [])
            title = "ROOT" if cid == "ROOT" else (self.graph.nodes[cid].title if cid in self.graph.nodes else cid)

            kc_labels, kc_vals = [], []
            for kid in kc_ids:
                n = self.graph.nodes.get(kid)
                if not n:
                    continue
                kc_labels.append(n.title)
                kc_vals.append(float(sess.mastery.get(kid, 0.0)))

            views[f"sec::{cid}"] = {
                "label": f"KCs: {title}",
                "labels": kc_labels,
                "values": kc_vals,
            }

        html = build_radar_dashboard_html("Radar — Sections & KCs", views, default_view="modules")

        return {
            "type": "radar",
            "data": {"name": "Radar — Sections & KCs", "buttonLabel": "Open radar", "html": html},
        }






    def _help_text(self) -> str:
        return (
            "Guide rapide de l'ITS\n\n"
            "Parcours conseille:\n"
            "1. Tape `start diagnostic` pour commencer l'estimation de niveau.\n"
            "2. Reponds au QCM diagnostic. Il sert seulement a estimer ton niveau, pas a valider les KCs.\n"
            "3. Lis la micro-lecon proposee pour la KC faible.\n"
            "4. Pose une question si quelque chose n'est pas clair.\n"
            "5. Tape `practice` pour lancer un QCM adapte a la KC.\n"
            "6. Si tu fais des erreurs, lis le feedback puis tape `hint` pour recevoir une aide progressive.\n"
            "7. Refais `practice` jusqu'a validation.\n"
            "8. Apres validation, tape `next` pour passer a la KC suivante.\n"
            "9. Tape `radar` pour voir ta progression.\n\n"
            "Commandes:\n"
            "- `start diagnostic`: demarrer le diagnostic global.\n"
            "- `practice`: generer un QCM adapte a la KC actuelle.\n"
            "- `hint`: obtenir l'indice suivant apres une erreur.\n"
            "- `next`: passer a la KC suivante apres validation.\n"
            "- `radar`: afficher la progression par KC/module.\n"
            "- `clear image`: oublier l'image active.\n\n"
            "Questions et images:\n"
            "- Pendant une micro-lecon, tu peux poser des questions texte sur la KC actuelle et les KCs precedentes.\n"
            "- Tu peux uploader une image de symbole et demander sa signification.\n"
            "- Les questions suivantes reutilisent la meme image jusqu'a `clear image`."
        )

    # =====================================================
    # MAIN ENTRY (called by chatkit_server.respond)
    # =====================================================
    async def handle(self, user_input: Any, ctx: AgentContext) -> Any:
        text = extract_latest_user_text(user_input).strip()
        image_urls = extract_latest_user_image_urls(user_input)
        low = text.lower()

        sess = self._get_sess(ctx)

        if image_urls:
            return await self._answer_visual_question(sess, text, image_urls, ctx)
        if low in {"clear image", "forget image", "new image"}:
            sess.last_visual_image_urls = []
            sess.visual_question_history = []
            return "Image oubliee. Ajoute une nouvelle image pour une autre analyse visuelle."
        if low in {"help", "guide", "aide", "commands", "commandes"}:
            return self._help_text()

        # ---- start diagnostic
        if low in {"start diagnostic", "diagnostic", "start"}:
            return await self._start_diagnostic(sess, ctx)

        # ---- practice on current weakness
        if low in {"practice", "practice qcm", "qcm"}:
            if not sess.current_kc_id:
                return "⚠️ No weakness KC selected yet. Type: start diagnostic"
            return await self._start_practice(sess, ctx)
        # ---- go to next KC and show micro-lesson
        if low in {"next", "next kc", "continue"}:
            if not sess.current_kc_id:
                return "⚠️ No current KC. Type: start diagnostic"
            return await self._next_kc_micro_lesson(sess, ctx)
        # ---- if user typed answers in chat (optional path)
        if low in {"checkpoint", "retry", "module quiz"}:
            if not sess.pending_module_id:
                return "⚠️ No module checkpoint pending."
            if not sess.pending_module_retry:
                return "⚠️ No retry requested. Submit the module quiz first."
            sess.pending_module_retry = False
            return await self._start_module_quiz(sess, sess.pending_module_id, ctx)
        if low in {"radar", "show radar", "evaluation radar"}:
            return await self._show_radar(sess)
        if low in {"hint", "next hint"}:
            return self._next_hint_text(sess)
        if low in {"debug its", "its debug", "show its state"}:
            lines = [
                f"scope={sess.scope}",
                f"phase={sess.phase}",
                f"current_kc_id={sess.current_kc_id}",
                f"last_tutor_action={sess.last_tutor_action or '(none)'}",
            ]
            if sess.current_kc_id:
                lines.append(f"attempts={sess.attempts_by_kc.get(sess.current_kc_id, 0)}")
                lines.append(f"misconceptions={sess.misconceptions.get(sess.current_kc_id, [])}")
            lines.append(f"evidence_events={len(sess.evidence_events)}")
            return "\n".join(lines)
        if low in {"debug mastery", "mastery debug", "show mastery"}:
            lines = [
                f"scope={sess.scope}",
                f"phase={sess.phase}",
                f"current_kc_id={sess.current_kc_id}",
            ]
            if not sess.mastery:
                lines.append("mastery=(empty)")
            else:
                for kid, val in sorted(sess.mastery.items()):
                    title = self.graph.nodes[kid].title if kid in self.graph.nodes else kid
                    last = sess.last_score_by_kc.get(kid, 0.0)
                    lines.append(f"{kid} | {title} | mastery={val:.3f} | latest={last:.3f}")
            if sess.diagnostic_profile:
                lines.append("diagnostic_profile=(screening only)")
                for kid, val in sorted(sess.diagnostic_profile.items()):
                    title = self.graph.nodes[kid].title if kid in self.graph.nodes else kid
                    raw = sess.diagnostic_raw_score_by_kc.get(kid, 0.0)
                    lines.append(f"{kid} | {title} | profile={val:.3f} | raw={raw:.3f}")
            return "\n".join(lines)


        if looks_like_answers(text):
            answers = parse_answers_from_text(text)
            return await self._process_answers(sess, answers, ctx)

        if sess.last_visual_image_urls and sess.last_tutor_action == "answer_visual_pdf_question":
            return await self._answer_visual_question(sess, text, [], ctx)

        if sess.current_kc_id and sess.phase != "waiting_answers":
            return await self._answer_learner_question(sess, text, ctx)

        # ---- default help
        return self._help_text()

    # =====================================================
    # INTERNAL STEPS
    # =====================================================
    async def _start_diagnostic(self, sess: Session, ctx: AgentContext) -> Any:
        kcs = self._kc_nodes_for_diagnostic()
        if not kcs:
            return "⚠️ No KCs found in kc_graph1.json."

        questions = await self.diagnostic_qcm.generate(kcs, DIAGNOSTIC_Q_NUM, ctx)

        # build hidden answers + mapping
        hidden: Dict[int, str] = {}
        q_to_kc: Dict[int, str] = {}
        q_text: Dict[int, dict] = {}

        for q in questions:
            num = int(q["number"])
            hidden[num] = str(q["answer"]).upper().strip()
            kc_id = str(q.get("kc_id") or "").strip()
            if kc_id not in self.graph.nodes:
                kc_id = kcs[0].id  # fallback
            q_to_kc[num] = kc_id

            q_text[num] = {"text": q["text"], "choices": q["choices"]}

        sess.scope = "diagnostic"
        sess.phase = "waiting_answers"
        sess.last_hidden_answers = hidden
        sess.last_question_to_kc = q_to_kc
        sess.last_question_text = q_text
        sess.last_tutor_action = "start_diagnostic"
        sess.pending_hint_ladder = []
        sess.hint_index = 0

        # server compatibility
        self.hidden_answers = hidden
        print(self.hidden_answers)
        self._record_event(sess, ctx, {
            "event": "diagnostic_started",
            "tutor_action": sess.last_tutor_action,
            "n_questions": len(questions),
            "kc_ids": [k.id for k in kcs],
        })
        data = qcm_widget_data(
            title=f"Global Diagnostic QCM — {self.graph.title}",
            questions=questions,
        )
        return {"type": "qcm", "data": data}

    async def _start_practice(self, sess: Session, ctx: AgentContext) -> Any:
        kc = self.graph.nodes.get(sess.current_kc_id or "")
        # ✅ RESET gate at the start of each practice attempt
        sess.can_advance = False
        sess.validated_kc_id = None
        if not kc:
            return "⚠️ Current KC not found."


        # Ensure we have a micro-lesson for this KC (Option B needs it)
        if not sess.current_micro_lesson.strip():
            sess.current_micro_lesson = await self._build_adaptive_micro_lesson(sess, kc, ctx)
            sess.last_mistakes_summary = ""

        micro = sess.current_micro_lesson.strip()
        mistakes = sess.last_mistakes_summary.strip() or "(No mistakes yet; first practice attempt.)"
        mastery = float(sess.mastery.get(kc.id, 0.0))
        attempts_before = int(sess.attempts_by_kc.get(kc.id, 0))
        difficulty = self.policy.select_difficulty(mastery, attempts_before)
        review_kc_ids = self.graph.previous_kcs(kc.id, limit=2)
        review_kcs = [self.graph.nodes[i] for i in review_kc_ids if i in self.graph.nodes]
        lesson_targets = extract_lesson_essentials(micro)
        kc_targets = sess.kc_essential_targets.get(kc.id)
        if kc_targets is None:
            kc_targets = await self.kc_targets.extract(kc, micro, ctx)
            sess.kc_essential_targets[kc.id] = kc_targets

        essential_targets = merge_essential_targets(
            kc_targets=kc_targets,
            lesson_targets=lesson_targets,
            limit=PRACTICE_MAX_Q,
        )
        if not essential_targets:
            essential_targets = lesson_targets or [kc.title]

        essential_count = len(essential_targets)
        min_q, max_q = estimate_practice_bounds_from_targets(
            essential_targets=essential_targets,
            mistakes_summary=mistakes,
            base_min=PRACTICE_MIN_Q,
            base_max=PRACTICE_MAX_Q,
            review_kc_count=len(review_kcs),
            attempts=attempts_before,
            difficulty=difficulty,
        )

        pack = await self.practice_qcm.generate_adaptive(
            kc,
            review_kcs,
            micro,
            mistakes,
            difficulty,
            min_q,
            max_q,
            essential_count,
            essential_targets,
            ctx,
        )
        n, questions = normalize_adaptive_practice_pack(pack, min_q, max_q)
        coverage_plan = pack.get("coverage_plan", []) if isinstance(pack, dict) else []
        missing_targets = missing_coverage_target_ids(essential_targets, coverage_plan)

        if missing_targets:
            try:
                repaired_pack = await self.practice_qcm.repair_coverage(
                    kc=kc,
                    review_kcs=review_kcs,
                    existing_pack=pack if isinstance(pack, dict) else {},
                    essential_targets=essential_targets,
                    missing_target_ids=missing_targets,
                    difficulty=difficulty,
                    min_questions=min_q,
                    max_questions=max_q,
                    ctx=ctx,
                )
                repaired_missing = missing_coverage_target_ids(
                    essential_targets,
                    repaired_pack.get("coverage_plan", []) if isinstance(repaired_pack, dict) else [],
                )
                if len(repaired_missing) <= len(missing_targets):
                    pack = repaired_pack
                    n, questions = normalize_adaptive_practice_pack(pack, min_q, max_q)
                    coverage_plan = pack.get("coverage_plan", []) if isinstance(pack, dict) else []
                    missing_targets = repaired_missing
            except Exception:
                pass

        # Validate questions shape
        def _is_valid_q(q: dict) -> bool:
            return (
                isinstance(q, dict)
                and isinstance(q.get("text"), str)
                and isinstance(q.get("choices"), list)
                and len(q["choices"]) == 4
                and str(q.get("answer", "")).upper() in {"A", "B", "C", "D"}
            )

        questions = [q for q in questions if _is_valid_q(q)]
        n = len(questions)

        # Hard fallback if model returned invalid JSON / invalid questions
        if n == 0:
            n = min_q
            questions = [{
                "number": i,
                "text": "Fallback question (model output invalid).",
                "choices": ["Option A", "Option B", "Option C", "Option D"],
                "answer": "A",
            } for i in range(1, n + 1)]

        hidden: Dict[int, str] = {}
        q_to_kc: Dict[int, str] = {}
        q_text: Dict[int, dict] = {}

        for q in questions:
            num = int(q["number"])
            hidden[num] = str(q["answer"]).upper().strip()
            q_to_kc[num] = kc.id
            q_text[num] = {
                "text": q["text"],
                "choices": q["choices"],
                "target_id": q.get("target_id", ""),
                "target": q.get("target", ""),
                "integrates_kc_ids": q.get("integrates_kc_ids", []),
            }

        sess.scope = "practice"
        sess.phase = "waiting_answers"
        sess.last_hidden_answers = hidden
        sess.last_question_to_kc = q_to_kc
        sess.last_question_text = q_text
        sess.attempts_by_kc[kc.id] = attempts_before + 1
        sess.last_tutor_action = f"generate_{difficulty}_practice"
        sess.pending_hint_ladder = []
        sess.hint_index = 0

        self.hidden_answers = hidden
        print(self.hidden_answers)
        self._record_event(sess, ctx, {
            "event": "practice_started",
            "tutor_action": sess.last_tutor_action,
            "kc_id": kc.id,
            "kc_title": kc.title,
            "difficulty": difficulty,
            "attempt": sess.attempts_by_kc[kc.id],
            "mastery_before": mastery,
            "n_questions": n,
            "practice_min_questions": min_q,
            "practice_max_questions": max_q,
            "lesson_essential_count": essential_count,
            "practice_length_strategy": {
                "basis": "pdf_kc_targets + lesson_targets + previous_kc_integration + mistakes + attempts + difficulty",
                "difficulty": difficulty,
                "attempts_before": attempts_before,
                "review_kc_count": len(review_kcs),
                "mistake_count": len(re.findall(r"\bQ\d+:", mistakes)),
                "kc_target_count": len(kc_targets),
                "lesson_target_count": len(lesson_targets),
            },
            "kc_essential_targets": kc_targets,
            "micro_lesson_essential_targets": lesson_targets,
            "lesson_essential_targets": essential_targets,
            "practice_essential_targets": essential_targets,
            "missing_coverage_target_ids": missing_targets,
            "coverage_plan": coverage_plan,
            "review_kc_ids": [item.id for item in review_kcs],
            "review_kc_titles": [item.title for item in review_kcs],
            "source_pages": self._kc_ref_pages(kc),
        })
        data = qcm_widget_data(
            title=f"Practice QCM — {kc.title} ({n} questions)",
            questions=questions,
        )
        return {"type": "qcm", "data": data}
    
    async def _start_module_quiz(self, sess: Session, module_id: str, ctx: AgentContext) -> Any:
        # build KC list for the module
        module_kc_ids = self.graph.module_kcs(module_id)
        module_kcs = [self.graph.nodes[i] for i in module_kc_ids if i in self.graph.nodes]

        if not module_kcs:
            # nothing to quiz -> unlock module and continue
            sess.module_gate_locked = False
            sess.pending_module_id = None
            return "⚠️ Module has no KCs to quiz."

        # choose number of questions (same heuristic)
        n_module_q = max(MODULE_MIN_Q, min(MODULE_MAX_Q, max(8, len(module_kcs) * 2)))

        questions = await self.module_qcm.generate(
            module_title=self.graph.nodes[module_id].title if module_id in self.graph.nodes else "Module",
            kc_list=module_kcs,
            n_questions=n_module_q,
            ctx=ctx,
        )

        # store quiz state
        hidden: Dict[int, str] = {}
        q_to_kc: Dict[int, str] = {}
        q_text: Dict[int, dict] = {}

        for q in questions:
            num = int(q["number"])
            hidden[num] = str(q["answer"]).upper().strip()
            kc_id = str(q.get("kc_id") or "").strip()
            if kc_id not in self.graph.nodes:
                kc_id = module_kcs[0].id
            q_to_kc[num] = kc_id
            q_text[num] = {"text": q["text"], "choices": q["choices"]}

        sess.scope = "module_quiz"
        sess.phase = "waiting_answers"
        sess.last_hidden_answers = hidden
        sess.last_question_to_kc = q_to_kc
        sess.last_question_text = q_text
        sess.last_tutor_action = "start_module_checkpoint"
        sess.pending_hint_ladder = []
        sess.hint_index = 0

        self.hidden_answers = hidden
        print(self.hidden_answers)
        self._record_event(sess, ctx, {
            "event": "module_checkpoint_started",
            "tutor_action": sess.last_tutor_action,
            "module_id": module_id,
            "module_title": self.graph.nodes[module_id].title if module_id in self.graph.nodes else "Module",
            "kc_ids": [k.id for k in module_kcs],
            "n_questions": len(questions),
        })

        data = qcm_widget_data(
            title=f"✅ Module Checkpoint — {self.graph.nodes[module_id].title if module_id in self.graph.nodes else 'Module'}",
            questions=questions,
        )
        return {"type": "qcm", "data": data}



    async def _process_answers(self, sess: Session, answers: Dict[int, str], ctx: AgentContext) -> Any:
        if sess.phase != "waiting_answers" or not sess.last_hidden_answers:
            return "⚠️ No active QCM. Type: start diagnostic"

        correct = sess.last_hidden_answers
        q_to_kc = sess.last_question_to_kc
        mastery_before = dict(sess.mastery)

        weakness_kc_id, overall, per_kc = self.scorer.find_weakness(q_to_kc, answers, correct)

        # update mastery (EMA)
        # update mastery (EMA) — FIXED (no 30% on first observation)
        for kc_id, (c_cnt, t_cnt) in per_kc.items():
            score = (c_cnt / t_cnt) if t_cnt else 1.0
            sess.last_score_by_kc[kc_id] = score

            if sess.scope == "diagnostic":
                sess.diagnostic_raw_score_by_kc[kc_id] = score
                sess.diagnostic_profile[kc_id] = diagnostic_screening_mastery(score)
                continue

            if sess.scope == "practice":
                alpha = 0.8
                evidence_score = score
            else:
                alpha = 0.4
                evidence_score = score

            if kc_id not in sess.mastery:
                sess.mastery[kc_id] = evidence_score
            else:
                old = sess.mastery[kc_id]
                sess.mastery[kc_id] = (1 - alpha) * old + alpha * evidence_score




        # DIAGNOSTIC => pick weakness then micro-lesson
        if sess.scope == "diagnostic":
            if not weakness_kc_id:
                return "✅ Diagnostic done, but I couldn't map weakness to a KC. Try practice."

            sess.current_kc_id = weakness_kc_id
            kc = self.graph.nodes.get(weakness_kc_id)
            if not kc:
                return "✅ Diagnostic done. Weakness KC missing in graph."

            # produce micro-lesson
            lesson_text = await self._build_adaptive_micro_lesson(sess, kc, ctx)
            sess.current_micro_lesson = lesson_text
            sess.last_mistakes_summary = ""
            sess.last_tutor_action = "diagnose_weak_kc_then_micro_lesson"

            sess.phase = "idle"
            self.hidden_answers = None
            self._record_event(sess, ctx, {
                "event": "diagnostic_submitted",
                "tutor_action": sess.last_tutor_action,
                "evidence_role": "screening_only",
                "mastery_interpretation": "Diagnostic estimates candidate weakness; it does not validate full KC mastery.",
                "diagnostic_mastery_cap": {
                    "min": DIAGNOSTIC_MIN_MASTERY,
                    "max": DIAGNOSTIC_MAX_MASTERY,
                },
                "overall_score": overall,
                "weakness_kc_id": weakness_kc_id,
                "weakness_kc_title": kc.title,
                "per_kc": per_kc,
                "diagnostic_raw_score_by_kc": dict(sess.diagnostic_raw_score_by_kc),
                "diagnostic_profile": dict(sess.diagnostic_profile),
                "mastery_before": mastery_before,
                "mastery_after": dict(sess.mastery),
                "mastery_update": "none_from_diagnostic",
                "source_pages": self._kc_ref_pages(kc),
            })

            screening_text = (
                "Diagnostic screening result: this quiz identifies a candidate weak KC; "
                "it does not prove full mastery of other KCs and does not validate/pass any KC.\n"
                "I will use it only to adapt the next lesson level.\n\n"
                f"Candidate weak KC: {kc.title}\n\n"
                f"{lesson_text}"
            )
            return self._build_lesson_with_refs(kc, screening_text)
        
        if sess.scope == "module_quiz":
            module_id = sess.pending_module_id
            module_score = overall

            wrong_items = self._build_wrong_items(sess, answers, correct)
            decision = self.policy.module_result(module_score)
            sess.last_tutor_action = decision.action

            # Always clear quiz buffers after submission (prevents stale state bugs)
            self._clear_quiz_state(sess)
            sess.phase = "idle"

            if module_id:
                sess.module_mastery[module_id] = module_score

            # ---------- FAIL: explain + regenerate module quiz ----------
            if module_score < MODULE_THRESHOLD:
                sess.module_gate_locked = True
                sess.pending_module_retry = True

                module_title = self.graph.nodes[module_id].title if (module_id and module_id in self.graph.nodes) else "Module"
                dummy_module_node = KCNode(id=module_id or "module", title=module_title, kind="module")

                expl = await self.explain_mistake.explain(dummy_module_node, wrong_items, ctx)
                sess.last_module_feedback = expl  # optional

                # clear QCM state
                sess.last_hidden_answers = {}
                sess.last_question_to_kc = {}
                sess.last_question_text = {}
                self.hidden_answers = None
                sess.scope = "idle"
                sess.phase = "idle"
                self._record_event(sess, ctx, {
                    "event": "module_checkpoint_submitted",
                    "tutor_action": decision.action,
                    "decision_reason": decision.reason,
                    "module_id": module_id,
                    "score": module_score,
                    "threshold": MODULE_THRESHOLD,
                    "wrong_items": wrong_items,
                    "mastery_before": mastery_before,
                    "mastery_after": dict(sess.mastery),
                })

                return (
                    f"{expl}\n\n"
                    f"❌ Module not validated (score={module_score:.0%}, need {MODULE_THRESHOLD:.0%}).\n"
                    f"➡️ Type: checkpoint  (or retry) to generate a new module quiz."
                )


            # ---------- PASS: unlock + auto-move to next KC ----------
            sess.module_gate_locked = False
            sess.pending_module_id = None

            nxt = sess.pending_next_kc_id
            self._record_event(sess, ctx, {
                "event": "module_checkpoint_submitted",
                "tutor_action": decision.action,
                "decision_reason": decision.reason,
                "module_id": module_id,
                "score": module_score,
                "threshold": MODULE_THRESHOLD,
                "wrong_items": wrong_items,
                "mastery_before": mastery_before,
                "mastery_after": dict(sess.mastery),
                "next_kc_id": nxt,
            })
            if not nxt or nxt not in self.graph.nodes:
                return f"✅ Module validated (score={module_score:.0%}). 🏁 End of course."

            # Move to next KC automatically
            sess.current_kc_id = nxt
            sess.scope = "practice"
            sess.phase = "idle"

            # reset per-KC adaptation + lock gate until KC practice passes
            sess.can_advance = False
            sess.validated_kc_id = None
            sess.pending_next_kc_id = None
            sess.last_mistakes_summary = ""
            sess.current_micro_lesson = ""

            kc = self.graph.nodes[nxt]
            lesson_text = await self._build_adaptive_micro_lesson(sess, kc, ctx)
            sess.current_micro_lesson = lesson_text

            text = (
                f"✅ Module validated (score={module_score:.0%}).\n"
                f"📘 Next KC: {kc.title}\n\n"
                f"{lesson_text}\n\n"
                f"➡️ Type: practice"
            )
            return self._build_lesson_with_refs(kc, text)




        # PRACTICE => pass/fail loop
        if sess.scope == "practice":
            kc_id = sess.current_kc_id
            kc = self.graph.nodes.get(kc_id or "") if kc_id else None
            if not kc:
                return "⚠️ Practice evaluated, but current KC missing."

            # determine score on this KC
            c_cnt, t_cnt = per_kc.get(kc.id, (0, len(correct)))
            practice_score = (c_cnt / max(1, t_cnt))
            # ✅ PASS => unlock "next" for THIS KC only

            if practice_score < THRESHOLD:
                # ✅ FAIL => keep next locked
                sess.can_advance = False
                sess.validated_kc_id = None

                wrong_items = self._build_wrong_items(sess, answers, correct)
                misconceptions = self.misconception_tracker.detect(kc, wrong_items)
                self._store_misconceptions(sess, misconceptions)
                decision = self.policy.practice_result(
                    score=practice_score,
                    mastery=float(sess.mastery.get(kc.id, 0.0)),
                    attempts=int(sess.attempts_by_kc.get(kc.id, 0)),
                    misconceptions=misconceptions,
                )
                sess.last_tutor_action = decision.action
                sess.pending_hint_ladder = self._build_hint_ladder(kc, misconceptions, wrong_items)
                sess.hint_index = 0

                latest_mistake_lines = []
                for wi in wrong_items[:8]:
                    q_short = (wi.get("question", "") or "")[:180]
                    latest_mistake_lines.append(
                        f"Q{wi['number']}: learner={wi.get('learner_letter','?')} "
                        f"correct={wi.get('correct_letter','?')} | {q_short}"
                    )
                latest_mistakes_summary = "\n".join(latest_mistake_lines)

                expl = await self.explain_mistake.explain(kc, wrong_items, ctx)
                lesson_text = await self._build_adaptive_micro_lesson(
                    sess,
                    kc,
                    ctx,
                    mistakes_summary=latest_mistakes_summary,
                )

                # ✅ store lesson + mistakes for adaptive practice
                sess.current_micro_lesson = lesson_text

                lines = []
                for wi in wrong_items[:8]:
                    q_short = (wi.get("question", "") or "")[:180]
                    lines.append(f"Q{wi['number']}: learner={wi.get('learner_letter','?')} correct={wi.get('correct_letter','?')} | {q_short}")
                sess.last_mistakes_summary = "\n".join(lines)


                sess.phase = "idle"
                self._clear_quiz_state(sess)
                self._record_event(sess, ctx, {
                    "event": "practice_submitted",
                    "tutor_action": decision.action,
                    "decision_reason": decision.reason,
                    "kc_id": kc.id,
                    "kc_title": kc.title,
                    "score": practice_score,
                    "threshold": THRESHOLD,
                    "passed": False,
                    "wrong_items": wrong_items,
                    "misconceptions": [obs.label for obs in misconceptions],
                    "mastery_before": mastery_before,
                    "mastery_after": dict(sess.mastery),
                    "attempt": sess.attempts_by_kc.get(kc.id, 0),
                    "source_pages": self._kc_ref_pages(kc),
                })
                hint_text = self._next_hint_text(sess)

                text = (
                    f"KC non validee: {kc.title}\n"
                    f"Score: {practice_score:.0%} (seuil: {THRESHOLD:.0%})\n\n"
                    f"{hint_text}\n\n"
                    f"{expl}"
                )
                return self._build_lesson_with_refs(kc, text)




            # ✅ PASS => unlock next for THIS KC
            sess.can_advance = True
            sess.validated_kc_id = kc.id
            decision = self.policy.practice_result(
                score=practice_score,
                mastery=float(sess.mastery.get(kc.id, 0.0)),
                attempts=int(sess.attempts_by_kc.get(kc.id, 0)),
                misconceptions=[],
            )
            sess.last_tutor_action = decision.action
            sess.pending_hint_ladder = []
            sess.hint_index = 0

            # store pending next (do NOT move now)
            nxt = self.graph.next_kc(kc.id)
            sess.pending_next_kc_id = nxt if (nxt and nxt in self.graph.nodes) else None
            cur_module = self.graph.module_of(kc.id)
            next_module = self.graph.module_of(nxt) if nxt else None
            sess.current_module_id = cur_module

            # if end-of-module (next KC is in another module OR no next KC)
            if cur_module and (not nxt or next_module != cur_module):
                sess.pending_module_id = cur_module
                sess.module_gate_locked = True
                sess.pending_module_retry = False
                self._record_event(sess, ctx, {
                    "event": "practice_submitted",
                    "tutor_action": "validate_kc_then_module_checkpoint",
                    "decision_reason": "KC validated and the next KC is outside the current module.",
                    "kc_id": kc.id,
                    "kc_title": kc.title,
                    "score": practice_score,
                    "threshold": THRESHOLD,
                    "passed": True,
                    "mastery_before": mastery_before,
                    "mastery_after": dict(sess.mastery),
                    "attempt": sess.attempts_by_kc.get(kc.id, 0),
                    "source_pages": self._kc_ref_pages(kc),
                    "module_id": cur_module,
                })
                return await self._start_module_quiz(sess, cur_module, ctx)

                
            # clear quiz state (keep current_kc_id as the validated KC!)
            sess.phase = "idle"
            self._clear_quiz_state(sess)
            self._record_event(sess, ctx, {
                "event": "practice_submitted",
                "tutor_action": decision.action,
                "decision_reason": decision.reason,
                "kc_id": kc.id,
                "kc_title": kc.title,
                "score": practice_score,
                "threshold": THRESHOLD,
                "passed": True,
                "mastery_before": mastery_before,
                "mastery_after": dict(sess.mastery),
                "attempt": sess.attempts_by_kc.get(kc.id, 0),
                "source_pages": self._kc_ref_pages(kc),
                "next_kc_id": sess.pending_next_kc_id,
            })

            if sess.pending_next_kc_id:
                next_kc = self.graph.nodes[sess.pending_next_kc_id]
                return (
                    f"✅ Validated KC: {kc.title} (score={practice_score:.0%}).\n"
                    f"➡️ Next KC: {next_kc.title}\n"
                    f"Type: next"
                )

            return (
                f"✅ Validated KC: {kc.title} (score={practice_score:.0%}).\n"
                f"🏁 No next KC. You finished the course sequence."
            )



        sess.phase = "idle"
        self.hidden_answers = None
        return "✅ Done."

    # =====================================================
    # OPTIONAL: hook for your server's qcm.submit action
    # If you later update chatkit_server.py, call this.
    # =====================================================
    async def handle_qcm_submit(self, submitted_answers: Dict[int, str], ctx: AgentContext) -> Any:
        sess = self._get_sess(ctx)
        return await self._process_answers(sess, submitted_answers, ctx)
