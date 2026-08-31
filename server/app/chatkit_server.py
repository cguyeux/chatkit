# chatkit_server.py

from __future__ import annotations
import base64
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncIterator
from pprint import pprint
import webbrowser  # for local dev only
from urllib.parse import unquote, urlparse

from agents import TContext  # type variable for context
from chatkit.agents import AgentContext, ThreadItemConverter
from chatkit.server import ChatKitServer
from chatkit.types import (
    ThreadMetadata,
    UserMessageItem,
    Action,
    WidgetItem,
    ThreadStreamEvent,
    AssistantMessageItem,
    AssistantMessageContent,
    ThreadItemDoneEvent,
    ThreadItem,
    AssistantMessageContent,
    UserMessageItem,
    ImageAttachment,
)
from openai.types.responses import ResponseInputImageParam, ResponseInputTextParam
from chatkit.store import Store, AttachmentStore
from chatkit.types import UserMessageItem as CKUserMessageItem, AssistantMessageItem as CKAssistantMessageItem
# 🔹 Import your multi-agent orchestrator
from app.orchestrator import Orchestrator
from app.widgets.qcmwidget import build_qcm_widget_from_data
from app.widgets.studywidget import build_study_widget_from_data
from app.widgets.mapwidget import build_map_widget_from_data   
from app.widgets.plotlywidget import build_plotly_widget_from_data
from app.widgets.radarwidget import build_radar_widget_from_data

class VisualThreadItemConverter(ThreadItemConverter):
    def _image_url_for_model(self, attachment: ImageAttachment) -> str:
        url = str(attachment.preview_url)
        parsed = urlparse(url)
        marker = "/static/"
        if marker not in parsed.path:
            return url

        static_rel = unquote(parsed.path.split(marker, 1)[1]).lstrip("/")
        app_dir = Path(__file__).resolve().parent
        path = (app_dir / static_rel).resolve()
        try:
            path.relative_to(app_dir.resolve())
        except ValueError:
            return url
        if not path.exists():
            return url

        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        return f"data:{attachment.mime_type};base64,{encoded}"

    async def attachment_to_message_content(self, attachment):
        if isinstance(attachment, ImageAttachment):
            return ResponseInputImageParam(
                type="input_image",
                image_url=self._image_url_for_model(attachment),
                detail="auto",
            )
        return ResponseInputTextParam(
            type="input_text",
            text=f"Unsupported attachment: {attachment.name} ({attachment.mime_type})",
        )


# ChatKit helper for converting thread messages
converter = VisualThreadItemConverter()



class MyChatKitServer(ChatKitServer[dict[str, Any]]):
    """ChatKit server that delegates logic to your Orchestrator."""

    def __init__(
        self,
        store: Store[TContext],
        attachment_store: AttachmentStore[TContext] | None = None,
    ):
        super().__init__(store=store, attachment_store=attachment_store)
        self.orch = Orchestrator()  # 🔹 attach orchestrator instance

    # ----------------------------------------------------------------------
    # MAIN CHAT RESPONSE
    # ----------------------------------------------------------------------
    async def respond(
        self,
        thread: ThreadMetadata,
        item: UserMessageItem | None,
        context: TContext,
    ) -> AsyncIterator[ThreadStreamEvent]:

        print("......////::",item)
        agent_context = AgentContext(
            thread=thread,
            store=self.store,
            request_context=context,
        )

        # 1) Load recent items (history)
        items_page = await self.store.load_thread_items(
            thread_id=thread.id,
            after=None,
            limit=20,
            order="desc",
            context=context,
        )
        items = list(reversed(items_page.data))

        # 2) Convert to input_items for Agents SDK
        input_items = await converter.to_agent_input(items)

        # 3) Call your orchestrator with input_items instead of plain string
        try:
            result_text = await self.orch.handle(user_input=input_items, ctx=agent_context)
        except Exception as e:
            result_text = f"⚠️ Internal error: {e}"
      

        if isinstance(result_text, dict):
            result_type = result_text.get("type")

            if result_type == "qcm":
                qcm_data = result_text["data"]
                print("QCM data:", qcm_data)

                widget_root = build_qcm_widget_from_data(qcm_data)

                widget_item = WidgetItem(
                    thread_id=thread.id,
                    id=self.store.generate_item_id("message", thread, context),
                    created_at=datetime.now(),
                    widget=widget_root,
                    title=qcm_data.get("title", "QCM"),
                )

                yield ThreadItemDoneEvent(item=widget_item)
                return
            if result_type == "radar":
                radar_data = result_text["data"]  # {title, html}
                widget_root = build_radar_widget_from_data(radar_data)

                widget_item = WidgetItem(
                    thread_id=thread.id,
                    id=self.store.generate_item_id("message", thread, context),
                    created_at=datetime.now(),
                    widget=widget_root,
                    title=radar_data.get("title", "Radar"),
                )

                yield ThreadItemDoneEvent(item=widget_item)
                return
            
            if result_type == "study":
                study_data = result_text["data"]
                widget_root = build_study_widget_from_data(study_data)
                payload = study_data.get("payload", {})

                widget_item = WidgetItem(
                    thread_id=thread.id,
                    id=self.store.generate_item_id("message", thread, context),
                    created_at=datetime.now(),
                    widget=widget_root,
                    title=payload.get("title", "Study card"),
                )

                yield ThreadItemDoneEvent(item=widget_item)
                return
            if result_type == "map":
                map_data = result_text["data"]
                print("MAP DATA:", map_data)
                widget_root = build_map_widget_from_data(map_data)

                widget_item = WidgetItem(
                    thread_id=thread.id,
                    id=self.store.generate_item_id("message", thread, context),
                    created_at=datetime.now(),
                    widget=widget_root,
                    title="Static map",
                )

                yield ThreadItemDoneEvent(item=widget_item)
                return
            if result_type == "plotly":
                plot_data = result_text["data"]  # expected: {"html": "...", "title": "..."} or similar
                print("PLOTLY DATA:", plot_data)

                widget_root = build_plotly_widget_from_data(plot_data)

                widget_item = WidgetItem(
                    thread_id=thread.id,
                    id=self.store.generate_item_id("message", thread, context),
                    created_at=datetime.now(),
                    widget=widget_root,
                    title=plot_data.get("title", "Plotly chart"),
                )

                yield ThreadItemDoneEvent(item=widget_item)
                return
            if result_type == "lesson_with_ref":
                lesson_text = str(result_text.get("text", "")).strip()
                if lesson_text:
                    message_item = AssistantMessageItem(
                        thread_id=thread.id,
                        id=self.store.generate_item_id("message", thread, context),
                        created_at=datetime.now(),
                        content=[AssistantMessageContent(text=lesson_text)],
                    )
                    yield ThreadItemDoneEvent(item=message_item)

                ref_widget = result_text.get("ref_widget")
                if isinstance(ref_widget, dict):
                    widget_root = build_plotly_widget_from_data(ref_widget)
                    widget_item = WidgetItem(
                        thread_id=thread.id,
                        id=self.store.generate_item_id("message", thread, context),
                        created_at=datetime.now(),
                        widget=widget_root,
                        title=ref_widget.get("title", "Source"),
                    )
                    yield ThreadItemDoneEvent(item=widget_item)
                return

        # else: normal text answer
        message_item = AssistantMessageItem(
            thread_id=thread.id,
            id=self.store.generate_item_id("message", thread, context),
            created_at=datetime.now(),
            content=[AssistantMessageContent(text=str(result_text))],
        )
        yield ThreadItemDoneEvent(item=message_item)
        
    # ----------------------------------------------------------------------
    # ACTION HANDLING (not used yet)
    # ----------------------------------------------------------------------
    async def action(
        self,
        _thread: ThreadMetadata,
        _action: Action[str, Any],
        _sender: WidgetItem | None,
        _context: TContext,
    ) -> AsyncIterator[ThreadStreamEvent]:

        if _action.type in ("map.open_external", "map.show_inline", "report.open"):
            print("[MyChatKitServer.action] client-side action received (ignored on server):",
                _action.type, _action.payload)
            return

        if _action.type == "qcm.submit":
            agent_context = AgentContext(
                thread=_thread,
                store=self.store,
                request_context=_context,
            )

            submitted_answers = self._extract_answers_from_payload(_action.payload)
            if not submitted_answers:
                evaluation_text = "⚠️ No answers received with the submission."
                message_item = AssistantMessageItem(
                    thread_id=_thread.id,
                    id=self.store.generate_item_id("message", _thread, _context),
                    created_at=datetime.now(),
                    content=[AssistantMessageContent(text=evaluation_text)],
                )
                yield ThreadItemDoneEvent(item=message_item)
                return

            # ✅ run the workflow step
            result = await self.orch.handle_qcm_submit(submitted_answers, agent_context)

            # render like respond()
            if isinstance(result, dict):
                rtype = result.get("type")

                if rtype == "qcm":
                    qcm_data = result["data"]
                    widget_root = build_qcm_widget_from_data(qcm_data)
                    widget_item = WidgetItem(
                        thread_id=_thread.id,
                        id=self.store.generate_item_id("message", _thread, _context),
                        created_at=datetime.now(),
                        widget=widget_root,
                        title=qcm_data.get("title", "QCM"),
                    )
                    yield ThreadItemDoneEvent(item=widget_item)
                    return

                if rtype == "study":
                    study_data = result["data"]
                    widget_root = build_study_widget_from_data(study_data)
                    payload = study_data.get("payload", {})
                    widget_item = WidgetItem(
                        thread_id=_thread.id,
                        id=self.store.generate_item_id("message", _thread, _context),
                        created_at=datetime.now(),
                        widget=widget_root,
                        title=payload.get("title", "Study card"),
                    )
                    yield ThreadItemDoneEvent(item=widget_item)
                    return

                if rtype == "lesson_with_ref":
                    lesson_text = str(result.get("text", "")).strip()
                    if lesson_text:
                        message_item = AssistantMessageItem(
                            thread_id=_thread.id,
                            id=self.store.generate_item_id("message", _thread, _context),
                            created_at=datetime.now(),
                            content=[AssistantMessageContent(text=lesson_text)],
                        )
                        yield ThreadItemDoneEvent(item=message_item)

                    ref_widget = result.get("ref_widget")
                    if isinstance(ref_widget, dict):
                        widget_root = build_plotly_widget_from_data(ref_widget)
                        widget_item = WidgetItem(
                            thread_id=_thread.id,
                            id=self.store.generate_item_id("message", _thread, _context),
                            created_at=datetime.now(),
                            widget=widget_root,
                            title=ref_widget.get("title", "Source"),
                        )
                        yield ThreadItemDoneEvent(item=widget_item)
                    return

            # fallback text
            message_item = AssistantMessageItem(
                thread_id=_thread.id,
                id=self.store.generate_item_id("message", _thread, _context),
                created_at=datetime.now(),
                content=[AssistantMessageContent(text=str(result))],
            )
            yield ThreadItemDoneEvent(item=message_item)
            return


        raise RuntimeError(f"Unsupported action type: {_action.type}")
    
    def _extract_answers_from_payload(self, payload: Any) -> dict[int, str]:
        """
        Normalize action payload from the QCM widget into {question_number: choice}.
        Supports payloads where answers live under `values.answers` or flat keys
        like `answers.1`.
        """
        normalized: dict[int, str] = {}
        data = payload if isinstance(payload, dict) else {}

        values = data.get("values")
        if not isinstance(values, dict):
            values = data

        raw_answers: dict[str, Any] = {}
        answers_section = values.get("answers")
        if isinstance(answers_section, dict):
            raw_answers = answers_section
        else:
            for key, value in values.items():
                if isinstance(key, str) and key.startswith("answers."):
                    raw_answers[key.split(".", 1)[1]] = value

        for key, value in raw_answers.items():
            try:
                question_number = int(str(key))
            except (TypeError, ValueError):
                continue

            if isinstance(value, str) and value:
                normalized[question_number] = value.strip().upper()

        return normalized
