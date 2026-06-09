"""Phase 0 — session scope helper and audit hook."""
import logging
import sys

sys.path.insert(0, "D:/real-time-voice/wwts-agent")
sys.path.insert(0, "D:/real-time-voice/server")

import pytest

from wwts_agent import api


def test_assert_wo_in_scope_accepts_matching_dict_codes():
    detail = {"custcode": "DELLQXS", "ordernum": "WU10090009"}
    codes = [{"code": "DELLQXS", "name": "Dell QXS"}]
    api._assert_wo_in_scope(detail, codes)


def test_assert_wo_in_scope_accepts_matching_string_codes():
    detail = {"custcode": "acme", "ordernum": "WU1"}
    api._assert_wo_in_scope(detail, ["ACME"])


def test_assert_wo_in_scope_rejects_out_of_scope():
    detail = {"custcode": "OTHER", "ordernum": "WU1"}
    with pytest.raises(ValueError, match="not in your authorized customer list"):
        api._assert_wo_in_scope(detail, [{"code": "DELLQXS", "name": "Dell"}])


def test_assert_wo_in_scope_rejects_missing_detail():
    with pytest.raises(ValueError, match="detail is missing"):
        api._assert_wo_in_scope({}, ["ACME"])


def test_assert_wo_in_scope_rejects_missing_custcode():
    with pytest.raises(ValueError, match="no customer code"):
        api._assert_wo_in_scope({"ordernum": "WU1"}, ["ACME"])


def test_assert_wo_in_scope_rejects_empty_customer_codes():
    detail = {"custcode": "ACME"}
    with pytest.raises(ValueError, match="No customer codes available"):
        api._assert_wo_in_scope(detail, [])


def test_normalize_customer_codes_mixed_formats():
    assert api._normalize_customer_codes("ACME") == ["ACME"]
    assert api._normalize_customer_codes([{"code": "A"}, "B"]) == ["A", "B"]
    assert api._normalize_customer_codes([{"code": "  "}, ""]) == []


def test_log_wwts_action_emits_audit_record(caplog):
    with caplog.at_level(logging.INFO, logger="wwts_agent.audit"):
        api.log_wwts_action(
            "create_wo",
            user_id="RSMITH",
            thread_id="thread-1",
            customer_code="DELLQXS",
            RC=0,
        )
    assert len(caplog.records) == 1
    message = caplog.records[0].message
    assert "wwts_audit" in message
    assert "action=create_wo" in message
    assert "user_id=RSMITH" in message
    assert "thread_id=thread-1" in message
    assert "customer_code=DELLQXS" in message
    assert "RC=0" in message
