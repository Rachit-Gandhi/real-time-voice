/** Shared WWTS auth helpers for login + voice console pages. */
(function (global) {
  'use strict';

  const AUTH_KEY = 'wwts_auth';

  function parseLoginResponse(body) {
    const parms = body?.data?.Parms || body?.data?.parms || {};
    return {
      userId: parms.UserID || parms.user_id || '',
      session: body.session ?? parms.Session ?? null,
      version: parms.Version || '',
      env: parms.Env || '',
      source: parms.Source || '',
      expireDays: parms.ExpireDays ?? null,
      rc: body.rc ?? parms.RC ?? 0,
      resultMsg: body.result_msg || parms.ResultMsg || '',
      raw: body,
    };
  }

  function getAuthContext() {
    try {
      const raw = sessionStorage.getItem(AUTH_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  }

  function setAuthContext(ctx) {
    sessionStorage.setItem(AUTH_KEY, JSON.stringify(ctx));
  }

  function clearAuthContext() {
    sessionStorage.removeItem(AUTH_KEY);
  }

  function requireAuth(loginPath) {
    if (!getAuthContext()) {
      window.location.replace(loginPath || '/login');
      return false;
    }
    return true;
  }

  global.WwtsAuth = {
    AUTH_KEY,
    parseLoginResponse,
    getAuthContext,
    setAuthContext,
    clearAuthContext,
    requireAuth,
  };
})(window);
