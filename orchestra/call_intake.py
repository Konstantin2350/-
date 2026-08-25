from dataclasses import dataclass

from orchestra.infrastructure import ProjectRecord
from orchestra.schemas import CallAnalysis, CallIntakeMetadata, TaskDraft
from orchestra.services import TaskService, lexical_roots


@dataclass(frozen=True)
class ProjectMatch:
    project_id: str | None
    name: str | None
    confidence: float
    reason: str


def match_project(
    projects: list[ProjectRecord],
    transcript: str,
    metadata: CallIntakeMetadata,
    threshold: float,
) -> ProjectMatch:
    if metadata.project_id:
        project_id = str(metadata.project_id)
        project = next((item for item in projects if item.id == project_id), None)
        if not project:
            raise ValueError("Project not found")
        return ProjectMatch(project.id, project.name, 1.0, "project_id supplied by caller")

    transcript_roots = lexical_roots(transcript)
    best: tuple[float, ProjectRecord, list[str]] | None = None
    for project in projects:
        name_roots = lexical_roots(project.name)
        descriptor_roots = lexical_roots(f"{project.name} {project.description}")
        overlap = transcript_roots & descriptor_roots
        score = len(overlap) / max(min(len(descriptor_roots), 8), 1)
        score += 0.2 if transcript_roots & name_roots else 0
        searchable = f"{project.name} {project.description}".lower()
        if metadata.contact_name and metadata.contact_name.lower() in searchable:
            score += 0.25
        if metadata.phone and metadata.phone in searchable:
            score += 0.25
        candidate = (min(score, 1.0), project, sorted(overlap))
        if best is None or candidate[0] > best[0]:
            best = candidate

    if best is None or best[0] < threshold:
        confidence = round(best[0], 3) if best else 0.0
        return ProjectMatch(None, None, confidence, "no confident project match")
    confidence, project, overlap = best
    terms = ", ".join(overlap[:8]) or "contact metadata"
    return ProjectMatch(
        project.id,
        project.name,
        round(confidence, 3),
        f"matched project terms: {terms}",
    )


def proposed_tasks(analysis: CallAnalysis, tasks: TaskService) -> list[TaskDraft]:
    return [tasks.create(item, []) for item in analysis.action_items]
