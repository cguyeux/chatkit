# app/orchestrator.py
from __future__ import annotations

import os
import json
import re
from urllib.parse import quote
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from agents import Agent, Runner, FileSearchTool, ModelSettings
from chatkit.agents import AgentContext
from app.viz.radar_html import build_radar_dashboard_html

# =====================================================
# CONFIG
# ===================================================== VECTOR_STORE_ID vs_6a1d49343a688191a1a714ca3dafc3d8  
VECTOR_STORE_ID = os.getenv("VECTOR_STORE_ID", "vs_6a116b3869e08191aa26f247b322a8c1")
KC_GRAPH_PATH = os.getenv("KC_GRAPH_PATH", os.path.join(os.path.dirname(__file__), "kc_graph1.json"))

DIAGNOSTIC_Q_NUM = int(os.getenv("DIAGNOSTIC_Q_NUM", "8"))# global diagnostic length
"""   
PRACTICE_Q_NUM = int(os.getenv("PRACTICE_Q_NUM", "3"))       # per-KC practice length""" 
THRESHOLD = float(os.getenv("MASTERY_THRESHOLD", "0.7"))     # pass threshold (0..1)

PRACTICE_MIN_Q = int(os.getenv("PRACTICE_MIN_Q", "3"))
PRACTICE_MAX_Q = int(os.getenv("PRACTICE_MAX_Q", "10"))
MODULE_THRESHOLD = float(os.getenv("MODULE_THRESHOLD", "0.7"))
MODULE_MIN_Q = int(os.getenv("MODULE_MIN_Q", "8"))
MODULE_MAX_Q = int(os.getenv("MODULE_MAX_Q", "20"))

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
    return str(input_items or "").strip()


def looks_like_answers(text: str) -> bool:
    # matches: 1A 2C 3B or 1 a,2 c ...
    return bool(re.search(r"\b\d+\s*[A-D]\b", text.upper()))


def parse_answers_from_text(text: str) -> Dict[int, str]:
    out: Dict[int, str] = {}
    s = text.upper().replace(",", " ")
    for m in re.finditer(r"\b(\d+)\s*([A-D])\b", s):
        out[int(m.group(1))] = m.group(2)
    return out


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
            "prompt": q["text"],
            "choices": [
                {"label": f"A) {c[0]}", "value": "A"},
                {"label": f"B) {c[1]}", "value": "B"},
                {"label": f"C) {c[2]}", "value": "C"},
                {"label": f"D) {c[3]}", "value": "D"},
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
    - len(questions) == n (truncate if too many)
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

    # if too short, we accept but will use len(questions)
    if len(questions) < n:
        n = max(min_q, len(questions))

    # renumber
    for i, q in enumerate(questions, start=1):
        if isinstance(q, dict):
            q["number"] = i

    return n, questions

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
                '  "questions": [\n'
                '    {"number":1,"text":"...","choices":["..","..","..",".."],"answer":"A"},\n'
                "    ...\n"
                "  ]\n"
                "}\n"
                "\n"
                "Rules:\n"
                "- n_questions must be between 3 and 10.\n"
                "- questions length MUST equal n_questions.\n"
                "- choices are 4 short options.\n"
                "- answer is one of A/B/C/D.\n"
                "- Focus on weak sub-points revealed by mistakes.\n"
            ),
            model_settings=ModelSettings(store=True),
        )

    async def generate_adaptive(
        self,
        kc: KCNode,
        micro_lesson_text: str,
        mistakes_summary: str,
        ctx: AgentContext,
    ) -> Dict[str, Any]:
        prompt = f"""
Build an ADAPTIVE practice QCM only about this KC:

KC title: "{kc.title}"
KC id: "{kc.id}"

Micro-lesson the learner received:
{micro_lesson_text}

Learner mistakes summary (if any):
{mistakes_summary}

Return ONLY JSON:
{{
  "n_questions": <int 3..10>,
  "questions": [
    {{"number":1,"text":"...","choices":["..","..","..",".."],"answer":"B"}},
    ...
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
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "You create a MODULE checkpoint multiple-choice quiz.\n"
                "Use ONLY doctrine content from file_search.\n"
                "Return ONLY valid JSON.\n"
                "Each question MUST include:\n"
                "- number (int)\n"
                "- text (string)\n"
                "- choices (array of 4 strings)\n"
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
    """Micro-lesson only on weakness KC (plain text, no widget, no JSON)."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Micro-lesson_Agent",
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "You teach a micro-lesson ONLY about the provided KC.\n"
                "Ground everything in doctrine using file_search.\n"
                "Return PLAIN TEXT ONLY (no JSON, no markdown code fences).\n"
                "Use this structure:\n"
                "1) Title\n"
                "2) What you must know (3-16 bullets)\n"
                "3) Operational example (short)\n"
                "4) Common mistakes (2-4 bullets)\n"
                "5) Quick self-check (2 short questions, no choices)\n"
            ),
            model_settings=ModelSettings(store=True),
        )

    async def build(self, kc: KCNode, ctx: AgentContext) -> str:
        prompt = f"""
Teach the learner a micro-lesson on this KC only.

KC title: "{kc.title}"
KC id: "{kc.id}"

Constraints:
- Keep it short and operational.
- Use file_search to ground definitions/rules.
- Plain text only.
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
        return (res.final_output or "").strip()




class ExplainMistakeAgent:
    """Explain mistakes when score below threshold."""

    def __init__(self) -> None:
        self.tool = FileSearchTool(max_num_results=8, vector_store_ids=[VECTOR_STORE_ID])
        self.agent: Agent[AgentContext] = Agent[AgentContext](
            name="Explain-mistake_Agent",
            model="gpt-4.1",
            tools=[self.tool],
            instructions=(
                "You explain the learner's mistakes briefly and clearly.\n"
                "Use doctrine from file_search.\n"
                "Output plain text (no JSON).\n"
                "Include: what the correct concept is, why the chosen option is wrong, and 1 quick tip."
            ),
            model_settings=ModelSettings(store=True),
        )

    async def explain(self, kc: KCNode, wrong_items: List[dict], ctx: AgentContext) -> str:
        prompt = f"""
The learner struggled on this KC: "{kc.title}" ({kc.id})

Here are wrong answers (each item includes question, choices, correct_letter, learner_letter):
{wrong_items}

Explain the mistakes, grounded in doctrine. Keep it concise and actionable.
"""
        res = await Runner.run(self.agent, prompt, context=ctx)
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

    # ✅ Option B memory
    current_micro_lesson: str = ""          # last generated micro-lesson for current KC
    last_mistakes_summary: str = ""         # compact summary used to adapt practice
    
    # ✅ NEW: gate for "next"
    can_advance: bool = False
    validated_kc_id: Optional[str] = None
    pending_next_kc_id: Optional[str] = None

    current_module_id: Optional[str] = None

    pending_module_id: Optional[str] = None     # module that must be validated by checkpoint
    module_gate_locked: bool = False            # True => must pass module quiz before next


    module_mastery: Dict[str, float] = field(default_factory=dict)

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
        self.scorer = ScoreFindWeaknessAgent()
        self.micro_lesson = MicroLessonAgent()
        self.practice_qcm = PracticeQcmAgent()
        self.explain_mistake = ExplainMistakeAgent()
        self.module_qcm = ModuleQcmAgent()
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
        pdf_url = f"http://127.0.0.1:8000/static/{quote(pdf_name)}#page={first_page}"
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
        lesson_text = await self.micro_lesson.build(kc, ctx)
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






    # =====================================================
    # MAIN ENTRY (called by chatkit_server.respond)
    # =====================================================
    async def handle(self, user_input: Any, ctx: AgentContext) -> Any:
        text = extract_latest_user_text(user_input).strip()
        low = text.lower()

        sess = self._get_sess(ctx)

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
            return "\n".join(lines)


        if looks_like_answers(text):
            answers = parse_answers_from_text(text)
            return await self._process_answers(sess, answers, ctx)

        # ---- default help
        return (
            "Commands:\n"
            "- start diagnostic\n"
            "- practice\n"
            "Then answer like: 1A 2C 3B (or submit the QCM widget)."
        )

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

        # server compatibility
        self.hidden_answers = hidden
        print(self.hidden_answers)
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
            sess.current_micro_lesson = await self.micro_lesson.build(kc, ctx)
            sess.last_mistakes_summary = ""

        micro = sess.current_micro_lesson.strip()
        mistakes = sess.last_mistakes_summary.strip() or "(No mistakes yet; first practice attempt.)"

        pack = await self.practice_qcm.generate_adaptive(kc, micro, mistakes, ctx)
        n, questions = normalize_adaptive_practice_pack(pack, PRACTICE_MIN_Q, PRACTICE_MAX_Q)

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
            n = PRACTICE_MIN_Q
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
            q_text[num] = {"text": q["text"], "choices": q["choices"]}

        sess.scope = "practice"
        sess.phase = "waiting_answers"
        sess.last_hidden_answers = hidden
        sess.last_question_to_kc = q_to_kc
        sess.last_question_text = q_text

        self.hidden_answers = hidden
        print(self.hidden_answers)
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

        self.hidden_answers = hidden
        print(self.hidden_answers)

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

        weakness_kc_id, overall, per_kc = self.scorer.find_weakness(q_to_kc, answers, correct)

        # update mastery (EMA)
        # update mastery (EMA) — FIXED (no 30% on first observation)
        for kc_id, (c_cnt, t_cnt) in per_kc.items():
            score = (c_cnt / t_cnt) if t_cnt else 1.0
            sess.last_score_by_kc[kc_id] = score

            if sess.scope == "practice":
                alpha = 0.8
            elif sess.scope == "diagnostic":
                alpha = 0.2
            else:
                alpha = 0.4

            if kc_id not in sess.mastery:
                sess.mastery[kc_id] = score
            else:
                old = sess.mastery[kc_id]
                sess.mastery[kc_id] = (1 - alpha) * old + alpha * score




        # DIAGNOSTIC => pick weakness then micro-lesson
        if sess.scope == "diagnostic":
            if not weakness_kc_id:
                return "✅ Diagnostic done, but I couldn't map weakness to a KC. Try practice."

            sess.current_kc_id = weakness_kc_id
            kc = self.graph.nodes.get(weakness_kc_id)
            if not kc:
                return "✅ Diagnostic done. Weakness KC missing in graph."

            # produce micro-lesson
            lesson_text = await self.micro_lesson.build(kc, ctx)
            sess.current_micro_lesson = lesson_text
            sess.last_mistakes_summary = ""

            sess.phase = "idle"
            self.hidden_answers = None

            return self._build_lesson_with_refs(kc, lesson_text)
        
        if sess.scope == "module_quiz":
            module_id = sess.pending_module_id
            module_score = overall

            # Build wrong_items for explanation
            wrong_items: List[dict] = []
            for qnum, corr in correct.items():
                u = answers.get(qnum, "")
                if u.upper() != corr.upper():
                    qinfo = sess.last_question_text.get(qnum, {})
                    wrong_items.append({
                        "number": qnum,
                        "question": qinfo.get("text", ""),
                        "choices": qinfo.get("choices", []),
                        "correct_letter": corr,
                        "learner_letter": u,
                    })

            # Always clear quiz buffers after submission (prevents stale state bugs)
            sess.last_hidden_answers = {}
            sess.last_question_to_kc = {}
            sess.last_question_text = {}
            self.hidden_answers = None
            sess.phase = "idle"

            if module_id:
                sess.module_mastery[module_id] = module_score

            # ---------- FAIL: explain + regenerate module quiz ----------
            if module_score < MODULE_THRESHOLD:
                sess.module_gate_locked = True
                sess.pending_module_retry = True

                # build wrong_items
                wrong_items = []
                for qnum, corr in correct.items():
                    u = answers.get(qnum, "")
                    if u.upper() != corr.upper():
                        qinfo = sess.last_question_text.get(qnum, {})
                        wrong_items.append({
                            "number": qnum,
                            "question": qinfo.get("text", ""),
                            "choices": qinfo.get("choices", []),
                            "correct_letter": corr,
                            "learner_letter": u,
                        })

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

                return (
                    f"{expl}\n\n"
                    f"❌ Module not validated (score={module_score:.0%}, need {MODULE_THRESHOLD:.0%}).\n"
                    f"➡️ Type: checkpoint  (or retry) to generate a new module quiz."
                )


            # ---------- PASS: unlock + auto-move to next KC ----------
            sess.module_gate_locked = False
            sess.pending_module_id = None

            nxt = sess.pending_next_kc_id
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
            lesson_text = await self.micro_lesson.build(kc, ctx)
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

                wrong_items: List[dict] = []
                for qnum, corr in correct.items():
                    u = answers.get(qnum, "")
                    if u.upper() != corr.upper():
                        qinfo = sess.last_question_text.get(qnum, {})
                        wrong_items.append({
                            "number": qnum,
                            "question": qinfo.get("text", ""),
                            "choices": qinfo.get("choices", []),
                            "correct_letter": corr,
                            "learner_letter": u,
                        })

                expl = await self.explain_mistake.explain(kc, wrong_items, ctx)
                lesson_text = await self.micro_lesson.build(kc, ctx)

                # ✅ store lesson + mistakes for adaptive practice
                sess.current_micro_lesson = lesson_text

                lines = []
                for wi in wrong_items[:8]:
                    q_short = (wi.get("question", "") or "")[:180]
                    lines.append(f"Q{wi['number']}: learner={wi.get('learner_letter','?')} correct={wi.get('correct_letter','?')} | {q_short}")
                sess.last_mistakes_summary = "\n".join(lines)


                sess.phase = "idle"
                self.hidden_answers = None

                text = (
                    f"{expl}\n\n"
                    f"---\n"
                    f"{lesson_text}\n\n"
                    f"➡️ Type: practice  (to retry the KC QCM)"
                )
                return self._build_lesson_with_refs(kc, text)




            # ✅ PASS => unlock next for THIS KC
            sess.can_advance = True
            sess.validated_kc_id = kc.id

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
                return await self._start_module_quiz(sess, cur_module, ctx)

                
            # clear quiz state (keep current_kc_id as the validated KC!)
            sess.phase = "idle"
            sess.last_hidden_answers = {}
            sess.last_question_to_kc = {}
            sess.last_question_text = {}
            self.hidden_answers = None

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
