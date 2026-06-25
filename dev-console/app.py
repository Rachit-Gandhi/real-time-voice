"""Agent-One developer console — text chat, ingest, and session monitor."""
import uuid
import httpx
import streamlit as st

st.set_page_config(
    page_title="Agent Dev Console",
    page_icon="🤖",
    layout="wide",
)

# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("🤖 Agent Dev Console")
    st.divider()
    agent_url = st.text_input("Agent-One URL", value="http://localhost:8001")
    wrapper_url = st.text_input("Voice-Wrapper URL", value="http://localhost:8000")
    st.divider()

    if "thread_id" not in st.session_state:
        st.session_state.thread_id = str(uuid.uuid4())[:8]

    st.text_input("Thread ID", key="thread_id")
    user_id = st.text_input("User ID", value="dev-user")

    if st.button("🔄 New Thread", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())[:8]
        st.session_state.chat_history = []
        st.rerun()

    st.divider()
    st.caption("Voice console → http://localhost:8000/console")

# ── Session state ─────────────────────────────────────────────────────────────
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# ── Tabs ──────────────────────────────────────────────────────────────────────
chat_tab, ingest_tab, sessions_tab, tickets_tab = st.tabs(["💬 Chat", "🌐 Ingest", "🎙️ Sessions", "🎫 Tickets"])

INTENT_ICON = {
    "website_qa":    "🔵",
    "sql_qa":        "🟢",
    "hybrid":        "🟣",
    "clarification": "🟡",
    "unsupported":   "🔴",
    "fallback":      "⚫",
}


def _invoke(message: str) -> dict | None:
    try:
        r = httpx.post(
            f"{agent_url}/agents/agent-one/invoke",
            json={
                "message": message,
                "thread_id": st.session_state.thread_id,
                "user_id": user_id,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        st.error(f"Cannot reach agent-one at **{agent_url}** — is it running?")
    except httpx.HTTPStatusError as exc:
        st.error(f"agent-one returned {exc.response.status_code}: {exc.response.text}")
    except Exception as exc:
        st.error(f"Unexpected error: {exc}")
    return None


# ── Chat tab ──────────────────────────────────────────────────────────────────
with chat_tab:
    for entry in st.session_state.chat_history:
        with st.chat_message(entry["role"]):
            st.write(entry["content"])

            if entry["role"] == "assistant" and "meta" in entry:
                meta = entry["meta"]
                intent = meta.get("intent") or "unknown"
                icon = INTENT_ICON.get(intent, "⚪")
                conf = meta.get("confidence", 0.0)

                cols = st.columns([3, 1, 1])
                cols[0].caption(f"{icon} intent: `{intent}`")
                cols[1].caption(f"confidence: `{conf:.2f}`")
                if meta.get("requires_followup"):
                    cols[2].caption("⚠️ needs follow-up")

                citations = meta.get("citations") or meta.get("sources") or []
                if citations:
                    with st.expander(f"📎 {len(citations)} citation(s)"):
                        for c in citations:
                            st.write(f"- {c}")

                speak = meta.get("speak", "")
                if speak and speak != entry["content"]:
                    with st.expander("🔊 Speak version"):
                        st.write(speak)

                with st.expander("🔧 Raw response"):
                    st.json(meta)

    if prompt := st.chat_input("Ask the agent…"):
        st.session_state.chat_history.append({"role": "user", "content": prompt})

        with st.spinner("Thinking…"):
            result = _invoke(prompt)

        if result:
            answer = result.get("answer") or "(no answer)"
            st.session_state.chat_history.append({
                "role": "assistant",
                "content": answer,
                "meta": result,
            })

        st.rerun()


# ── Ingest tab ────────────────────────────────────────────────────────────────
with ingest_tab:
    st.subheader("Website Ingestion")

    col1, col2 = st.columns([4, 1])
    start_url = col1.text_input("Start URL", placeholder="https://example.com")
    max_pages = col2.number_input("Max pages", min_value=1, max_value=200, value=10)

    website_id = st.text_input(
        "Website ID",
        value="default",
        help="Logical name for the site in the vector store. Re-ingesting with the same ID replaces existing chunks.",
    )

    if st.button("🕷️ Start Ingestion", disabled=not start_url):
        with st.spinner(f"Crawling {start_url} …"):
            try:
                r = httpx.post(
                    f"{agent_url}/agents/agent-one/ingest",
                    json={
                        "start_url": start_url,
                        "max_pages": int(max_pages),
                        "website_id": website_id,
                    },
                    timeout=180,
                )
                r.raise_for_status()
                data = r.json()

                c1, c2, c3 = st.columns(3)
                c1.metric("Status", data.get("status", "ok"))
                c2.metric("Pages crawled", data.get("pages_crawled", 0))
                c3.metric("Chunks indexed", data.get("chunks_indexed", 0))
                st.success("Ingestion complete. The agent will use these chunks on the next query.")

            except httpx.ConnectError:
                st.error(f"Cannot reach agent-one at **{agent_url}** — is it running?")
            except httpx.HTTPStatusError as exc:
                st.error(f"Ingest failed ({exc.response.status_code}): {exc.response.text}")
            except Exception as exc:
                st.error(f"Unexpected error: {exc}")


# ── Sessions tab ──────────────────────────────────────────────────────────────
with sessions_tab:
    st.subheader("Voice Session Inspector")
    st.caption(
        f"Open the voice console at **{wrapper_url}**, start a call, "
        "then select or paste a session ID below to inspect its state."
    )

    # ── List all sessions ─────────────────────────────────────────────────────
    if "selected_session_id" not in st.session_state:
        st.session_state.selected_session_id = ""

    col_list, _ = st.columns([1, 3])
    do_list = col_list.button("📋 List All Sessions", use_container_width=True)

    if do_list:
        try:
            r = httpx.get(f"{wrapper_url}/voice/sessions", timeout=5)
            r.raise_for_status()
            sessions = r.json()

            if not sessions:
                st.info("No sessions found.")
            else:
                st.write(f"**{len(sessions)} session(s):**")
                for s in sessions:
                    sid = s.get("session_id", "")
                    status = s.get("status", "unknown")
                    agent = s.get("agent_id", "")
                    user = s.get("user_id", "")
                    started = (s.get("started_at") or "")[:19]
                    badge = "🟢" if status == "active" else "⚫"

                    col_info, col_select = st.columns([5, 1])
                    col_info.markdown(
                        f"{badge} `{sid}` &nbsp;·&nbsp; **{agent}** &nbsp;·&nbsp; "
                        f"user: `{user}` &nbsp;·&nbsp; {started}"
                    )
                    if col_select.button("Select", key=f"sel_{sid}"):
                        st.session_state.selected_session_id = sid
                        st.rerun()

        except httpx.ConnectError:
            st.error(f"Cannot reach voice-wrapper at **{wrapper_url}** — is it running?")
        except Exception as exc:
            st.error(f"Error: {exc}")

    st.divider()

    # ── Inspect a specific session ────────────────────────────────────────────
    session_id_input = st.text_input(
        "Session ID",
        value=st.session_state.selected_session_id,
        placeholder="Paste or select a session_id above",
    )

    col_fetch, col_end = st.columns([1, 1])
    do_fetch = col_fetch.button("🔍 Fetch", disabled=not session_id_input)
    do_end = col_end.button("🛑 End Session", disabled=not session_id_input)

    if do_fetch:
        try:
            r = httpx.get(
                f"{wrapper_url}/voice/session/{session_id_input}/status",
                timeout=5,
            )
            if r.status_code == 404:
                st.warning("Session not found.")
            else:
                r.raise_for_status()
                data = r.json()

                status = data.get("status", "unknown")
                if status == "active":
                    st.success(f"Status: **{status}**")
                else:
                    st.info(f"Status: **{status}**")

                c1, c2 = st.columns(2)
                c1.write(f"**Session ID:** `{data.get('session_id')}`")
                c1.write(f"**Agent:** `{data.get('agent_id')}`")
                c1.write(f"**User:** `{data.get('user_id')}`")
                c2.write(f"**Started:** `{data.get('started_at')}`")

                turns = data.get("transcript") or []
                if turns:
                    st.write(f"**Conversation ({len(turns)} turns):**")
                    for turn in turns:
                        role = turn.get("role", "")
                        text = turn.get("text", "")
                        ts   = (turn.get("ts") or "")[:19]
                        if role == "user":
                            st.markdown(
                                f"<div style='text-align:left; color:#3dd68c; margin:4px 0'>"
                                f"<small>{ts}</small><br><b>You:</b> {text}</div>",
                                unsafe_allow_html=True,
                            )
                        else:
                            st.markdown(
                                f"<div style='text-align:right; color:#e8533a; margin:4px 0'>"
                                f"<small>{ts}</small><br><b>Agent:</b> {text}</div>",
                                unsafe_allow_html=True,
                            )
                elif data.get("last_transcript"):
                    st.write("**Last user message:**")
                    st.info(data["last_transcript"])

                with st.expander("Full session JSON"):
                    st.json(data)

        except httpx.ConnectError:
            st.error(f"Cannot reach voice-wrapper at **{wrapper_url}** — is it running?")
        except Exception as exc:
            st.error(f"Error: {exc}")

    if do_end:
        try:
            r = httpx.post(
                f"{wrapper_url}/voice/session/{session_id_input}/end",
                timeout=5,
            )
            r.raise_for_status()
            st.success("Session ended.")
            st.session_state.selected_session_id = ""
        except httpx.ConnectError:
            st.error(f"Cannot reach voice-wrapper at **{wrapper_url}** — is it running?")
        except Exception as exc:
            st.error(f"Error: {exc}")


# ── Tickets tab ───────────────────────────────────────────────────────────────
_STATUS_OPTIONS = ["open", "in_progress", "resolved", "closed"]
_STATUS_BADGE = {
    "open": "🟠",
    "in_progress": "🔵",
    "resolved": "🟢",
    "closed": "⚫",
}

with tickets_tab:
    st.subheader("L1 Support Tickets")

    col_refresh, col_search = st.columns([1, 3])
    do_refresh = col_refresh.button("🔄 Refresh", use_container_width=True)
    search_emp = col_search.text_input("Filter by employee number", placeholder="e.g. EMP-1234")

    if "tickets_data" not in st.session_state:
        st.session_state.tickets_data = []

    if do_refresh or (not st.session_state.tickets_data):
        try:
            r = httpx.get(f"{agent_url}/agents/l1-support/tickets", timeout=10)
            r.raise_for_status()
            st.session_state.tickets_data = r.json()
        except httpx.ConnectError:
            st.error(f"Cannot reach agent-one at **{agent_url}** — is it running?")
        except Exception as exc:
            st.error(f"Error fetching tickets: {exc}")

    tickets = st.session_state.tickets_data
    if search_emp:
        tickets = [t for t in tickets if (t.get("employee_number") or "").lower() == search_emp.strip().lower()]

    if not tickets:
        st.info("No tickets found." if not search_emp else f"No tickets for employee **{search_emp}**.")
    else:
        st.caption(f"Showing **{len(tickets)}** ticket(s)")

        for ticket in tickets:
            tid    = ticket.get("ticket_id", "")
            status = ticket.get("status", "open")
            badge  = _STATUS_BADGE.get(status, "⚪")
            company = ticket.get("company_name", "")
            app     = ticket.get("application_name", "")
            name    = ticket.get("contact_name") or "—"
            emp_no  = ticket.get("employee_number") or "—"
            created = (ticket.get("created_at") or "")[:19]

            label = f"{badge} `{tid}` · {company} / {app} · {name} (#{emp_no}) · {created} · **{status}**"

            with st.expander(label):
                col_left, col_right = st.columns(2)

                col_left.write(f"**Ticket ID:** `{tid}`")
                col_left.write(f"**Company:** {company}")
                col_left.write(f"**Application:** {app}")
                col_left.write(f"**Site:** {ticket.get('site_id') or '—'}")
                col_left.write(f"**Product Ref:** {ticket.get('product_reference') or '—'}")

                col_right.write(f"**Contact:** {name}")
                col_right.write(f"**Employee #:** {emp_no}")
                col_right.write(f"**Email:** {ticket.get('contact_email') or '—'}")
                col_right.write(f"**Created:** {created}")
                col_right.write(f"**Email sent:** {'✅' if ticket.get('email_sent') else '❌'}")

                st.write("**Issue:**")
                st.info(ticket.get("issue_description") or "—")

                st.divider()
                status_col, btn_col = st.columns([2, 1])
                new_status = status_col.selectbox(
                    "Change status",
                    options=_STATUS_OPTIONS,
                    index=_STATUS_OPTIONS.index(status) if status in _STATUS_OPTIONS else 0,
                    key=f"status_{tid}",
                )
                if btn_col.button("Update", key=f"update_{tid}"):
                    try:
                        r = httpx.patch(
                            f"{agent_url}/agents/l1-support/tickets/{tid}/status",
                            json={"status": new_status},
                            timeout=5,
                        )
                        r.raise_for_status()
                        st.success(f"Ticket `{tid}` updated to **{new_status}**.")
                        # Refresh the local cache
                        for t in st.session_state.tickets_data:
                            if t.get("ticket_id") == tid:
                                t["status"] = new_status
                        st.rerun()
                    except httpx.ConnectError:
                        st.error(f"Cannot reach agent-one at **{agent_url}**.")
                    except Exception as exc:
                        st.error(f"Update failed: {exc}")
