from latest_ai_development.stages.reporting_stage import ReportingStage
from latest_ai_development.stages.research_stage import ResearchStage

STAGE_REGISTRY = {
    "research": ResearchStage,
    "reporting": ReportingStage,
}
