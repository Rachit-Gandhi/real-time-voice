"""API execution node — calls WWTS and formats results into natural language."""
from wwts_agent.state import WWTSState
from wwts_agent import api


def execute(state: WWTSState) -> WWTSState:
    stage = state.get("stage", "")
    user_id = state.get("user_id", "")
    context = state.get("context") or {}
    session = context.get("wwts_session")
    # Accept either customer_codes (list from login) or legacy customer_code (string)
    customer_codes = context.get("customer_codes") or context.get("customer_code") or []

    if not session:
        msg = "No active WWTS session. Please log in first."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    if stage == "executing_list":
        return _do_list(state, user_id, session, customer_codes)
    if stage == "executing_get":
        return _do_get(state, user_id, session)
    if stage == "executing_create":
        return _do_create(state, user_id, session)

    msg = "Unknown execution stage."
    return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}


def _do_list(state: WWTSState, user_id: str, session: int, customer_codes) -> WWTSState:
    wo_status = state.get("wo_status") or "O"
    days_back = state.get("wo_days_back") or (90 if wo_status != "O" else 30)
    result = api.list_workorders(user_id, session, customer_codes, days_back=days_back, status=wo_status)
    if not result["success"]:
        msg = f"Could not retrieve work orders: {result.get('error', 'unknown error')}."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    _status_label = {"O": "open", "C": "closed", "A": "open or closed"}.get(wo_status, wo_status)

    orders = result["orders"]
    if not orders:
        msg = f"No {_status_label} work orders found in the last {days_back} days."
        return {**state, "stage": "done", "wo_list": [], "final_answer": msg, "speak": msg, "requires_more_info": False}

    lines = [f"Found {len(orders)} {_status_label} work order(s):\n"]
    for o in orders[:15]:
        wo_num = o.get("ordernum", "")
        cust_call = o.get("custcall", "")
        city = o.get("city", "")
        status = o.get("laststop", "")
        model = o.get("model", "")
        csr = o.get("csr", "")
        ref = f" | Ref: {cust_call}" if cust_call else ""
        tech = f" | Tech: {csr}" if csr else ""
        lines.append(f"• WO {wo_num}{ref} — {model} — {city} — {status}{tech}")

    if len(orders) > 15:
        lines.append(f"... and {len(orders) - 15} more.")

    msg = "\n".join(lines)
    speak = f"Found {len(orders)} {_status_label} work orders. " + (
        f"The first one is WO {orders[0].get('ordernum', '')} in {orders[0].get('city', '')}."
        if orders else ""
    )
    return {
        **state,
        "stage": "done",
        "wo_list": orders,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _do_get(state: WWTSState, user_id: str, session: int) -> WWTSState:
    wo_number = state.get("wo_number", "")
    result = api.get_workorder(user_id, session, wo_number)

    if not result["success"]:
        error_detail = result.get("error", "")
        if error_detail:
            msg = f"Work order {wo_number} could not be retrieved: {error_detail}."
        else:
            msg = f"Work order {wo_number} was not found."
        return {**state, "stage": "done", "final_answer": msg, "speak": msg, "requires_more_info": False}

    d = result["detail"]
    remarks = result["remarks"]

    lines = [
        f"Work Order: {d.get('ordernum', wo_number)}",
        f"Status:     {d.get('vstatus', 'Unknown')}",
        f"Customer:   {d.get('custname', '')}",
        f"End User:   {d.get('endcust', '')}",
        f"Model:      {d.get('equip_model', '')}  Serial: {d.get('equip_serial', '')}",
        f"Location:   {d.get('city', '')}, {d.get('state', '')}  {d.get('zip', '')}",
        f"Contact:    {d.get('contactname', '')}  {d.get('contactphone', '')}",
        f"Opened:     {d.get('opened', '')}",
        f"Last Stop:  {d.get('laststop', '')}",
        f"Tech (CSR): {d.get('CSR', '')}",
    ]
    if d.get("eta"):
        lines.append(f"ETA:        {d['eta']}")

    if remarks:
        lines.append(f"\nActivity History ({len(remarks)} entries):")
        for r in remarks[-10:]:
            dt = r.get("entdatetime", "")
            author = r.get("author", "")
            text = (r.get("remdata") or "").strip()
            lines.append(f"  [{dt}] {author}: {text}")
    else:
        lines.append("\nNo remarks on file.")

    msg = "\n".join(lines)
    speak = (
        f"Work order {d.get('ordernum', wo_number)} status is {d.get('vstatus', 'unknown')}. "
        f"It was opened on {d.get('opened', 'unknown date')} and the last stop is {d.get('laststop', 'unknown')}."
    )
    return {
        **state,
        "stage": "done",
        "wo_detail": d,
        "wo_remarks": remarks,
        "final_answer": msg,
        "speak": speak,
        "requires_more_info": False,
    }


def _do_create(state: WWTSState, user_id: str, session: int) -> WWTSState:
    create_fields = api._normalize_fields(state.get("create_fields") or {})
    has_site = bool(create_fields.get("Site ID"))
    has_partial_location = bool(
        create_fields.get("Customer City") or create_fields.get("Customer Postal Code")
    )
    if not has_site and has_partial_location and not create_fields.get("Customer State"):
        msg = (
            "Please provide the customer state as well so I can create the work order "
            "with the city, state, and postal code."
        )
        return {
            **state,
            "stage": "collecting_create",
            "create_fields": create_fields,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    result = api.create_workorder(user_id, session, create_fields)

    if result["success"]:
        wo_num = result.get("OrderNum", "")
        customer = create_fields.get("Customer Code", "")
        wo_display = wo_num or "(check WWTS portal)"
        msg = (
            f"Work order created successfully!\n"
            f"WO Number:  {wo_display}\n"
            f"Customer:   {customer}"
        )
        speak = (
            f"Work order {wo_num} has been created for customer {customer}."
            if wo_num else
            f"Work order submitted for customer {customer}. Please check the WWTS portal for the WO number."
        )
        return {
            **state,
            "stage": "done",
            "created_wo_number": wo_num,
            "final_answer": msg,
            "speak": speak,
            "requires_more_info": False,
        }

    # Address/location error — ask user to correct, don't hard-fail
    if api._is_address_error(result.get("ResultMsg", "")):
        bad_site = create_fields.get("Site ID", "")
        cleaned = {k: v for k, v in create_fields.items() if k != "Site ID"}
        if bad_site:
            msg = (
                f"The Site ID '{bad_site}' wasn't found in the system. "
                "Could you please provide the customer city and postal code instead, "
                "or double-check the Site ID?"
            )
        else:
            msg = (
                "The address information provided isn't valid. "
                "Could you please provide the customer city, state, and postal code?"
            )
        return {
            **state,
            "stage": "collecting_create",
            "create_fields": cleaned,
            "final_answer": msg,
            "speak": msg,
            "requires_more_info": True,
        }

    # Generic non-address failure
    msg = f"Failed to create work order: {result.get('ResultMsg', 'unknown error')}."
    return {
        **state,
        "stage": "done",
        "final_answer": msg,
        "speak": msg,
        "requires_more_info": False,
    }
