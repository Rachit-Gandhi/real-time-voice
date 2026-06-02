"""WWITS GTAccess authentication routes."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from requests import RequestException

from portals.wwits.apis.rest_services import GTAccess
from portals.wwits.environment import Environment, wwits_env

DEFAULT_ENVIRONMENT = "QA"
DEFAULT_SOURCE = "WMP"

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    success: bool
    rc: int
    result_msg: str
    session: Optional[int] = None
    data: Dict[str, Any]
    customer_codes: list[Dict[str, str]] = Field(default_factory=list)
    # [{"code": "ACME", "name": "Acme Corp"}, ...]


def init_wwits_environment() -> None:
    """Initialize WWITS env once; GTAccess reads the module-level wwits_env singleton."""
    if (
        wwits_env.is_init
        and wwits_env.environment == DEFAULT_ENVIRONMENT
        and wwits_env.source == DEFAULT_SOURCE
    ):
        return
    try:
        Environment(
            environment=DEFAULT_ENVIRONMENT,
            source=DEFAULT_SOURCE,
            config_file=wwits_env.config,
            path="",
        )
    except Exception:
        # Singleton may already be configured from a prior request in this process.
        if wwits_env.environment != DEFAULT_ENVIRONMENT or wwits_env.source != DEFAULT_SOURCE:
            raise


@router.post("/gtaccess/login", response_model=LoginResponse)
def gtaccess_login(payload: LoginRequest) -> LoginResponse:
    init_wwits_environment()

    try:
        response = GTAccess().start_session(
            user=payload.user_id,
            password=payload.password,
        )
    except RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Unable to reach WWITS Access API: {exc}",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"WWITS Access API returned an invalid response: {exc}",
        ) from exc

    session_id = response.get("Session") if response.success else None

    customer_codes: list[Dict[str, str]] = []
    if response.success and session_id:
        try:
            cust_resp = GTAccess().UserCustomers(payload.user_id, session_id)
            if cust_resp.success:
                customer_codes = [
                    {"code": c.Customer, "name": c.Name}
                    for c in cust_resp.results()
                ]
        except Exception:
            pass

    return LoginResponse(
        success=response.success,
        rc=response.RC,
        result_msg=response.ResultMsg,
        session=session_id,
        data=response.as_dict(),
        customer_codes=customer_codes,
    )
