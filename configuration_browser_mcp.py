"""Register request/status only. No MCP operation can approve a review."""
from pydantic import BaseModel, ConfigDict, Field
from configuration_browser import runtime_service
from source_configuration_workflow import SourceReviewRequest


class ConfigurationReviewStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_id: str = Field(pattern=r"^cr_[0-9a-f]{32}$")


def register_configuration_browser_tools(mcp, outputs_root, project_data_root):
    @mcp.tool()
    def request_candidate_configuration_review(request: SourceReviewRequest) -> dict:
        """Prepare an expiring browser review of this exact project-specific crosswalk.

        Consequential local state write: obtain permission before requesting.
        No default pilot crosswalk. Rebuilds actual source/proposal/acreage review.
        Returns a review ID and controlled HTTPS page, not an approved crosswalk.
        Human operator must authenticate separately in their browser. Never ask
        for the operator credential in chat. Opening the URL does not approve.
        Does not save a crosswalk, classify, download, map, polygonize, or export.
        Disabled unless storage and independent operator authentication configured.
        """
        try:
            return runtime_service(outputs_root, project_data_root).request_review(
                request.model_dump(mode="json"))
        except Exception:
            return {"status": "review_request_failed", "configuration_saved": False,
                    "error": "Review unavailable, invalid, disabled, or capacity reached. No configuration approved."}

    @mcp.tool()
    def check_candidate_configuration_review(request: ConfigurationReviewStatusRequest) -> dict:
        """Read a browser review's state using its exact returned review ID.

        No approval, save, mapping, or export. Approved status validates saved
        configuration and approval evidence before returning configuration_id.
        That ID is the controlled JSON filename accepted by the existing mapping
        tool's required crosswalk_filename field. Carry it exactly; do not guess.
        Mapping needs separate applicable authorization and a matching acquisition.
        """
        try:
            return runtime_service(outputs_root, project_data_root).status(request.review_id)
        except Exception:
            return {"status": "review_status_failed", "configuration_saved": False,
                    "error": "Review unavailable or saved evidence failed validation. Do not map."}
