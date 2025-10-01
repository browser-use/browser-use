"""
Job Search Agent Script for Gathering and Deduplicating Job Postings
===================================================================

This script leverages the `browser_use` library to automate job searches
across multiple job boards and save the results into a CSV file.  It
builds upon the existing examples found in the `browser-use` repository,
particularly ``examples/use-cases/find_and_apply_to_jobs.py``.  The
primary differences are:

1. **Custom Data Model** – A simplified ``Job`` model captures only the
   columns requested by the user: job title, company, description,
   requirements, and salary.  No additional metadata is stored.

2. **Deduplication** – A lightweight in-memory deduplication mechanism
   computes a Jaccard similarity over tokenized job descriptions.  If
   the similarity between a new posting and any previously saved
   posting exceeds 0.9, the posting is discarded as a duplicate.

3. **Role‑Based Task Generation** – The script accepts a list of role
   names (e.g. ``Commercial Analyst``, ``Data Analyst``) and spawns an
   agent for each role.  Each agent is instructed to search the
   specified job boards (Seek, Indeed, LinkedIn) and use the
   ``save_job`` action to persist results.

4. **Configurable Runtime** – Command line flags and environment
   variables make it easy to customise the CSV path, deduplication
   threshold, model name, search location, job boards, number of roles,
   and maximum number of postings per role without editing the script.

Before running this script you should:

* Install the ``browser-use`` package and its dependencies.
* Provide valid API keys in your environment variables (e.g. ``OPENAI_API_KEY``).
* Ensure that Playwright’s Chromium is installed (``uvx playwright install chromium --with-deps --no-shell``).

Note: Because each agent interacts with live websites, consider running
only one agent at a time if you are concerned about rate limits or
computational resources.  For demonstration purposes the code below
runs agents sequentially.

"""

from __future__ import annotations

import argparse
import asyncio
import csv
import logging
import re
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, List, Sequence, Set

from dotenv import load_dotenv
from pydantic import BaseModel, field_validator

# Extend the Python path so that this script can import browser_use when
# executed from within the examples directory.  This mirrors the
# technique used throughout the ``examples`` folder in the upstream repo.
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from browser_use import Agent, ChatOpenAI, Tools


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv()  # Load environment variables (e.g. API keys)

logger = logging.getLogger(__name__)
if not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
logger.setLevel(logging.INFO)

# Path to the CSV file where jobs will be stored.  If the file does not
# exist it will be created automatically.
JOBS_CSV: Path = Path(os.getenv("JOB_OUTPUT_PATH", "jobs.csv"))

# List of role names to search for.  These strings are directly
# interpolated into the agent’s task prompts.  Feel free to add or
# remove entries based on your interests.  This list is drawn from
# earlier guidance on Melbourne‑based analyst roles.
DEFAULT_ROLE_LIST: List[str] = [
    "Commercial Analyst",
    "Financial Analyst",
    "FP&A Analyst",
    "Pricing Analyst",
    "Revenue Analyst",
    "Data Analyst (Finance)",
    "BI Analyst",
    "Product Analyst",
    "Operations Analyst",
    "Marketing Analyst",
    "Growth Analyst",
    "Systems Accountant",
    "Finance Systems Analyst",
    "ERP Analyst",
    "EPM Analyst",
    "Credit Risk Analyst",
    "Operational Risk Analyst",
    "Technology Risk Analyst",
    "Internal Auditor",
    "AML/KYC Analyst",
    "Fraud Analyst",
    "Business Analyst (Finance Systems)",
    "Finance Transformation Analyst",
    "Strategy Analyst",
    "Analytics Consultant",
    "Investment Analyst",
    "Valuations Analyst",
    "Corporate Finance Analyst",
    "Transaction Services Analyst",
    "Portfolio Analyst",
    "Payments Analyst",
    "Settlements Analyst",
    "Reconciliations Analyst",
    "Data Operations Analyst",
    "Budget Analyst",
    "Policy Analyst",
    "Supply Chain Analyst",
    "Forecast Analyst",
    "Revenue Operations Analyst",
    "FinOps Analyst",
]


# ---------------------------------------------------------------------------
# Deduplication Helper Functions
# ---------------------------------------------------------------------------


def _split_comma_separated(value: str) -> List[str]:
    """Split a comma separated string into a list of cleaned values."""

    return [item.strip() for item in value.split(",") if item.strip()]


def _format_list_for_prompt(items: Sequence[str]) -> str:
    """Return a human friendly string ("a", "a and b", "a, b, and c")."""

    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _deduplicate_preserve_order(items: Iterable[str]) -> List[str]:
    """Return a list with duplicates removed while keeping original order."""

    seen = set()
    result: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


DEFAULT_LOCATION = "Melbourne, Victoria, Australia"
DEFAULT_JOB_BOARDS = ["Seek", "Indeed", "LinkedIn"]
DEFAULT_MAX_POSTINGS = 30
DEFAULT_MODEL_NAME = "gpt-4.1-mini"
DEFAULT_DEDUP_THRESHOLD = 0.9


@dataclass(slots=True)
class JobSearchConfig:
    """Configuration container for controlling job search behaviour."""

    roles: List[str] = field(default_factory=lambda: list(DEFAULT_ROLE_LIST))
    location: str = DEFAULT_LOCATION
    job_boards: List[str] = field(default_factory=lambda: list(DEFAULT_JOB_BOARDS))
    max_postings: int = DEFAULT_MAX_POSTINGS
    csv_path: Path = JOBS_CSV
    dedup_threshold: float = DEFAULT_DEDUP_THRESHOLD
    model_name: str = DEFAULT_MODEL_NAME

    def __post_init__(self) -> None:
        cleaned_roles = _deduplicate_preserve_order(
            role.strip() for role in self.roles if isinstance(role, str)
        )
        if not cleaned_roles:
            raise ValueError("At least one role must be provided.")
        self.roles = cleaned_roles

        cleaned_boards = _deduplicate_preserve_order(
            board.strip() for board in self.job_boards if isinstance(board, str)
        )
        if not cleaned_boards:
            raise ValueError("At least one job board must be provided.")
        self.job_boards = cleaned_boards

        self.location = self.location.strip() or DEFAULT_LOCATION
        if self.max_postings <= 0:
            raise ValueError("max_postings must be a positive integer.")
        if not 0 < self.dedup_threshold <= 1:
            raise ValueError("dedup_threshold must be between 0 (exclusive) and 1 (inclusive).")

        self.csv_path = Path(self.csv_path)

    @property
    def job_boards_for_prompt(self) -> str:
        return _format_list_for_prompt(self.job_boards)

    @property
    def max_postings_for_prompt(self) -> str:
        return f"around {self.max_postings}" if self.max_postings else "a reasonable number of"

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON serialisable representation useful for logging."""

        return {
            "roles": self.roles,
            "location": self.location,
            "job_boards": self.job_boards,
            "max_postings": self.max_postings,
            "csv_path": str(self.csv_path),
            "dedup_threshold": self.dedup_threshold,
            "model_name": self.model_name,
        }

TOKEN_PATTERN = re.compile(r"[^a-zA-Z\s]")


def normalize_text(text: str) -> Set[str]:
    """Normalize a string into a set of lowercase tokens for Jaccard.

    This helper removes punctuation and splits on whitespace.  It
    intentionally retains repeated words in the set (duplicates are
    naturally discarded) and ignores numeric values.

    Args:
        text: The raw text to normalize.

    Returns:
        A set of lowercase alphanumeric tokens.
    """
    # Lowercase and remove any non‑letter characters.
    cleaned = TOKEN_PATTERN.sub(" ", text.lower())
    tokens = set(word for word in cleaned.split() if word)
    return tokens


def jaccard_similarity(set_a: Set[str], set_b: Set[str]) -> float:
    """Compute the Jaccard similarity between two sets.

    The Jaccard similarity is defined as the size of the intersection
    divided by the size of the union.  A result of 1.0 means the sets
    are identical; 0.0 means they share no elements.

    Args:
        set_a: First set of tokens.
        set_b: Second set of tokens.

    Returns:
        The Jaccard similarity coefficient.
    """
    if not set_a and not set_b:
        return 1.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


class DeduplicationIndex:
    """Maintain a deduplication index based on job description similarity.

    This class loads existing job descriptions from the output CSV (if
    present) and stores normalized token sets.  When new jobs are added
    via ``add_job()``, their descriptions are compared against all
    existing entries; if any pair exceeds the threshold, the job is
    skipped.

    Attributes:
        threshold: The Jaccard similarity threshold above which a job
            is considered a duplicate.  Defaults to 0.9.
        descriptions: A list of normalized token sets for previously
            saved jobs.
    """

    def __init__(self, csv_path: Path, threshold: float = 0.9) -> None:
        self.csv_path = csv_path
        self.threshold = threshold
        self.descriptions: List[Set[str]] = []
        if csv_path.exists():
            self._load_existing()

    def _load_existing(self) -> None:
        """Load existing job descriptions from the CSV file into memory."""
        try:
            with self.csv_path.open(newline="", encoding="utf-8") as f:
                reader = csv.reader(f)
                for index, row in enumerate(reader):
                    if not row:
                        continue
                    if index == 0 and [cell.lower() for cell in row[:5]] == [
                        "title",
                        "company",
                        "description",
                        "requirements",
                        "salary",
                    ]:
                        # Skip header row
                        continue
                    if len(row) >= 3:
                        description = row[2]
                        normalized = normalize_text(description)
                        self.descriptions.append(normalized)
        except Exception as exc:
            logger.warning(f"Failed to load existing jobs from {self.csv_path}: {exc}")

    def is_duplicate(self, description: str) -> bool:
        """Return True if the description is a near‑duplicate of an existing one."""
        new_set = normalize_text(description)
        for existing_set in self.descriptions:
            if jaccard_similarity(new_set, existing_set) >= self.threshold:
                return True
        return False

    def add(self, description: str) -> None:
        """Register a description in the deduplication index."""
        self.descriptions.append(normalize_text(description))


dedup_index = DeduplicationIndex(JOBS_CSV, threshold=DEFAULT_DEDUP_THRESHOLD)


def configure_job_storage(csv_path: Path, threshold: float) -> None:
    """Update the global CSV path and rebuild the deduplication index."""

    global JOBS_CSV, dedup_index
    JOBS_CSV = Path(csv_path)
    if JOBS_CSV.parent and not JOBS_CSV.parent.exists():
        JOBS_CSV.parent.mkdir(parents=True, exist_ok=True)
    dedup_index = DeduplicationIndex(JOBS_CSV, threshold=threshold)


# ---------------------------------------------------------------------------
# Pydantic Models and Tool Actions
# ---------------------------------------------------------------------------

class Job(BaseModel):
    """Model representing a job posting for the ``save_job`` tool."""

    title: str
    company: str
    description: str
    requirements: str
    salary: str | None = None

    @field_validator("title", "company", "description", "requirements", "salary", mode="before")
    @classmethod
    def _strip_strings(cls, value: Any) -> Any:
        """Trim whitespace from incoming strings while preserving ``None``."""

        if value is None:
            return None
        if isinstance(value, str):
            return value.strip()
        return value


tools = Tools()


@tools.action(
    "Save a job posting to CSV – deduplicating by description",
    param_model=Job,
)
def save_job(job: Job) -> str:
    """Persist a job posting to the CSV file if it is not a duplicate.

    The job description is normalized and compared to previous
    descriptions using a Jaccard similarity threshold.  Duplicate jobs
    are silently ignored.  The CSV file is created with a header if it
    does not yet exist.

    Args:
        job: The job object containing the fields to write.

    Returns:
        A message indicating whether the job was saved or skipped.
    """
    job_data = job.model_dump()
    description: str = job_data["description"]

    if not description:
        return "Job skipped: description is empty."

    # Check for duplicates
    if dedup_index.is_duplicate(description):
        return "Duplicate job skipped"

    # Append to CSV
    file_exists = JOBS_CSV.exists()
    with JOBS_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["title", "company", "description", "requirements", "salary"])
        writer.writerow(
            [
                job_data["title"],
                job_data["company"],
                description,
                job_data["requirements"],
                job_data.get("salary") or "",
            ]
        )

    # Update dedup index
    dedup_index.add(description)
    logger.info(f"Saved job: {job_data['title']} at {job_data['company']}")
    return "Job saved"


@tools.action("Read all saved jobs from CSV")
def read_saved_jobs() -> str:
    """Return the contents of the jobs CSV for later inspection."""
    if not JOBS_CSV.exists():
        return "No jobs have been saved yet."
    with JOBS_CSV.open(encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Agent Task Construction
# ---------------------------------------------------------------------------


def _read_roles_from_file(path: str) -> List[str]:
    """Load roles from a text file (one role per line, ``#`` comments allowed)."""

    try:
        with Path(path).expanduser().open(encoding="utf-8") as handle:
            roles: List[str] = []
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                roles.append(line)
            return roles
    except OSError as exc:  # pragma: no cover - depends on filesystem
        raise ValueError(f"Unable to read roles file '{path}': {exc}") from exc


def _read_int_env(var_name: str, default: int) -> int:
    raw = os.getenv(var_name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid integer for %s: %s – using default %s", var_name, raw, default)
        return default


def _read_float_env(var_name: str, default: float) -> float:
    raw = os.getenv(var_name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid float for %s: %s – using default %s", var_name, raw, default)
        return default


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command line arguments for the job search agent."""

    parser = argparse.ArgumentParser(description="Automate job searches with browser_use agents.")
    parser.add_argument(
        "--role",
        dest="roles",
        action="append",
        metavar="ROLE",
        help="Role title to search for. Can be provided multiple times.",
    )
    parser.add_argument(
        "--roles-file",
        dest="roles_file",
        metavar="PATH",
        help="Path to a text file containing one role per line.",
    )
    parser.add_argument(
        "--location",
        metavar="LOCATION",
        help="Location string to include in the agent instructions.",
    )
    parser.add_argument(
        "--boards",
        metavar="BOARD1,BOARD2",
        help="Comma separated list of job boards to target.",
    )
    parser.add_argument(
        "--max-postings",
        type=int,
        metavar="N",
        help="Maximum number of postings each agent should gather.",
    )
    parser.add_argument(
        "--csv-path",
        metavar="PATH",
        help="Location on disk to write the collected job data.",
    )
    parser.add_argument(
        "--model",
        dest="model_name",
        metavar="MODEL",
        help="LLM model identifier to use with ChatOpenAI.",
    )
    parser.add_argument(
        "--dedup-threshold",
        type=float,
        metavar="VALUE",
        help="Jaccard similarity threshold for detecting duplicate descriptions.",
    )
    parser.add_argument(
        "--list-default-roles",
        action="store_true",
        help="Print the built-in role list and exit.",
    )
    return parser.parse_args(argv)


def build_config_from_sources(args: argparse.Namespace) -> JobSearchConfig:
    """Combine CLI arguments and environment variables into a config object."""

    roles: List[str] = []
    if args.roles:
        roles.extend(args.roles)

    processed_files: Set[str] = set()
    for path in [args.roles_file, os.getenv("JOB_ROLES_FILE")]:
        if not path or path in processed_files:
            continue
        roles.extend(_read_roles_from_file(path))
        processed_files.add(path)

    if not roles:
        env_roles = os.getenv("JOB_ROLES")
        if env_roles:
            roles.extend(_split_comma_separated(env_roles))

    if not roles:
        roles = list(DEFAULT_ROLE_LIST)

    boards_source = args.boards or os.getenv("JOB_BOARDS")
    job_boards = _split_comma_separated(boards_source) if boards_source else list(DEFAULT_JOB_BOARDS)

    location = args.location or os.getenv("JOB_LOCATION") or DEFAULT_LOCATION

    max_postings = args.max_postings if args.max_postings is not None else _read_int_env(
        "JOB_MAX_POSTINGS", DEFAULT_MAX_POSTINGS
    )
    dedup_threshold = (
        args.dedup_threshold
        if args.dedup_threshold is not None
        else _read_float_env("JOB_DEDUP_THRESHOLD", DEFAULT_DEDUP_THRESHOLD)
    )
    csv_path_str = args.csv_path or os.getenv("JOB_OUTPUT_PATH") or str(JOBS_CSV)
    model_name = args.model_name or os.getenv("JOB_MODEL_NAME") or DEFAULT_MODEL_NAME

    return JobSearchConfig(
        roles=roles,
        location=location,
        job_boards=job_boards,
        max_postings=max_postings,
        csv_path=Path(csv_path_str),
        dedup_threshold=dedup_threshold,
        model_name=model_name,
    )

def build_task_prompt(role: str, config: JobSearchConfig) -> str:
    """Construct a natural language prompt instructing the agent to search for jobs.

    The prompt embeds configuration such as the location, job boards and
    collection limit.  It instructs the agent to extract only the fields
    required by the ``save_job`` tool and to avoid duplicates.

    Args:
        role: The job title or keyword to search for.
        config: The job search configuration.

    Returns:
        A multi‑line string ready to pass into the ``Agent`` initializer.
    """
    job_boards = config.job_boards_for_prompt
    limit_phrase = config.max_postings_for_prompt
    return (
        f"You are a job research assistant. Search for '{role}' roles in {config.location} on {job_boards}. "
        "For each unique job posting you find, extract the following fields: job title, company name, job "
        "description, job requirements, and salary (if listed). After extracting these details, call the "
        "'save_job' tool with a Job object containing those fields. Avoid saving duplicate postings: if a job "
        "description looks the same as one you've already saved, skip it. Do not apply for jobs; simply "
        f"collect and record the data. Once you have gathered {limit_phrase} postings or there are no more "
        "relevant listings, stop."
    )


async def run_agent_for_role(role: str, config: JobSearchConfig, model: ChatOpenAI) -> None:
    """Execute a single agent for the supplied role with error handling."""

    prompt = build_task_prompt(role, config)
    agent = Agent(task=prompt, llm=model, tools=tools)
    logger.info("Starting job search for role '%s'", role)
    try:
        await agent.run()
        logger.info("Completed job search for role '%s'", role)
    except Exception:  # pragma: no cover - defensive logging for runtime issues
        logger.exception("Agent run failed for role '%s'", role)


async def run_agents_sequentially(config: JobSearchConfig) -> None:
    """Run one agent per role sequentially to avoid overwhelming resources."""

    if not config.roles:
        logger.warning("No roles supplied; exiting early.")
        return

    logger.info("Starting job search session with config: %s", config.as_dict())
    model = ChatOpenAI(model=config.model_name)
    for role in config.roles:
        await run_agent_for_role(role, config, model)


def main(argv: Sequence[str] | None = None) -> None:
    """Entry point for synchronous execution."""

    args = parse_arguments(argv)
    if args.list_default_roles:
        for role in DEFAULT_ROLE_LIST:
            print(role)
        return

    try:
        config = build_config_from_sources(args)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(1) from exc

    configure_job_storage(config.csv_path, config.dedup_threshold)

    try:
        asyncio.run(run_agents_sequentially(config))
    except KeyboardInterrupt:  # pragma: no cover - interactive use
        logger.info("Job search interrupted by user.")


if __name__ == "__main__":
    main()