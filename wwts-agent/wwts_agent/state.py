from typing import TypedDict


class WWTSState(TypedDict, total=False):
    # Identity / session
    thread_id: str
    user_id: str          # WWTS user ID (e.g. "RSMITH")
    user_message: str
    messages: list        # [{"role": "user"|"assistant", "content": str}]
    context: dict         # wwts_session (int), customer_code (str)

    # Conversation FSM
    # greeting → intent → collecting_wo_number | collecting_create
    # → executing_list | executing_get | executing_create → done
    stage: str
    intent: str | None    # list_wo | get_wo | create_wo

    # Get WO detail
    wo_number: str | None
    wo_detail: dict | None
    wo_remarks: list | None

    # List WOs
    wo_list: list | None
    wo_status: str | None      # "O" = open (default), "C" = closed, "A" = all
    wo_days_back: int | None   # look-back window; closed searches default to 90

    # Create WO
    create_fields: dict
    created_wo_number: str | None

    # Output
    final_answer: str
    speak: str
    requires_more_info: bool
