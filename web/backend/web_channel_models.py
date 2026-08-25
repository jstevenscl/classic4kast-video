"""Pydantic request models for web_channels -- kept out of routes.py (which
already carries the full weather-channel model set) so a diff of routes.py
never touches this feature; see web_channel_routes.py for where these are
consumed."""

from pydantic import BaseModel, model_validator

_SOURCE_TYPES = {"url", "grafana"}


class WebChannelCreate(BaseModel):
    slug: str
    channel_name: str
    source_type: str = "url"
    enabled: bool = True
    render_mode: str = "on_demand"

    target_url: str | None = None
    viewport_width: int = 1280
    viewport_height: int = 720
    screenshot_interval_ms: int = 1000
    page_load_wait_ms: int = 2000
    device_scale_factor: float = 1.0
    # Optional CSS selector clicked once after page load, before capture
    # starts -- dismisses cookie banners/first-visit welcome modals that
    # would otherwise sit in every screenshot. Ignored for source_type
    # 'grafana' (no page/browser involved there at all).
    dismiss_selector: str | None = None

    grafana_base_url: str | None = None
    grafana_dashboard_uid: str | None = None
    grafana_panel_id: str | None = None
    grafana_api_token: str | None = None
    grafana_org_id: int = 1
    grafana_time_from: str = "now-1h"
    grafana_time_to: str = "now"
    grafana_extra_query: str | None = None

    @model_validator(mode="after")
    def _check_source_fields(self):
        if self.source_type not in _SOURCE_TYPES:
            raise ValueError(f"source_type must be one of {sorted(_SOURCE_TYPES)}")
        if self.source_type == "url" and not (self.target_url or "").strip():
            raise ValueError("target_url is required when source_type is 'url'")
        if self.source_type == "grafana":
            missing = [
                name for name, value in (
                    ("grafana_base_url", self.grafana_base_url),
                    ("grafana_dashboard_uid", self.grafana_dashboard_uid),
                    ("grafana_panel_id", self.grafana_panel_id),
                ) if not (value or "").strip()
            ]
            if missing:
                raise ValueError(f"source_type 'grafana' requires: {', '.join(missing)}")
        return self


class WebChannelUpdate(BaseModel):
    channel_name: str | None = None
    source_type: str | None = None
    enabled: bool | None = None
    render_mode: str | None = None

    target_url: str | None = None
    viewport_width: int | None = None
    viewport_height: int | None = None
    screenshot_interval_ms: int | None = None
    page_load_wait_ms: int | None = None
    device_scale_factor: float | None = None
    dismiss_selector: str | None = None

    grafana_base_url: str | None = None
    grafana_dashboard_uid: str | None = None
    grafana_panel_id: str | None = None
    grafana_api_token: str | None = None
    grafana_org_id: int | None = None
    grafana_time_from: str | None = None
    grafana_time_to: str | None = None
    grafana_extra_query: str | None = None


class WebChannelRenderResult(BaseModel):
    slug: str
    success: bool
    error: str | None = None


class GrafanaTestRequest(BaseModel):
    grafana_base_url: str
    grafana_dashboard_uid: str
    grafana_panel_id: str
    grafana_api_token: str | None = None
    grafana_org_id: int = 1


# ── Dispatcharr deploy (mirrors routes.py's DeployRequest/BulkDeployRequest/
# UpdateChannelProfilesRequest exactly -- kept as a separate copy here rather
# than imported, same reasoning as this module's own docstring: a diff of
# routes.py should never need to touch this feature and vice versa) ────────

class WebChannelDeployRequest(BaseModel):
    connection_id: int
    channel_group_id: int
    name: str | None = None
    stream_profile_id: int | None = None
    logo_url: str | None = None
    channel_profile_ids: list[int] | None = None


class WebChannelBulkDeployRequest(BaseModel):
    connection_ids: list[int]
    channel_group_name: str
    stream_profile_name: str | None = None
    name: str | None = None
    logo_url: str | None = None
    channel_profile_names: list[str] | None = None


class WebChannelUpdateChannelProfilesRequest(BaseModel):
    channel_profile_ids: list[int]


# ── Interactive login-session capture (see web_channel_routes.py's
# websocket bridge + webchannel-renderer/src/login_session.js) ─────────────

class WebChannelSessionCapture(BaseModel):
    cookies: list[dict]
    local_storage: dict[str, str]
