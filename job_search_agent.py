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

import asyncio
import csv
import logging
import os
import sys
from pathlib import Path
from typing import Any, List, Set

from dotenv import load_dotenv
from pydantic import BaseModel

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
logger.setLevel(logging.INFO)

# Path to the CSV file where jobs will be stored.  If the file does not
# exist it will be created automatically.
JOBS_CSV: Path = Path(os.getenv("JOB_OUTPUT_PATH", "jobs.csv"))

# List of role names to search for.  These strings are directly
# interpolated into the agent’s task prompts.  Feel free to add or
# remove entries based on your interests.  This list is drawn from
# earlier guidance on Melbourne‑based analyst roles.
ROLE_LIST: List[str] = [
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
    import re

    # Lowercase and remove any non‑letter characters.
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", text.lower())
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
            with self.csv_path.open(newline="") as f:
                reader = csv.reader(f)
                # Skip header if present (expecting five columns)
                for row in reader:
                    if len(row) >= 5:
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


dedup_index = DeduplicationIndex(JOBS_CSV, threshold=0.9)


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
    # Check for duplicates
    if dedup_index.is_duplicate(job.description):
        return "Duplicate job skipped"

    # Append to CSV
    file_exists = JOBS_CSV.exists()
    with JOBS_CSV.open("a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["title", "company", "description", "requirements", "salary"])
        writer.writerow([job.title, job.company, job.description, job.requirements, job.salary or ""])

    # Update dedup index
    dedup_index.add(job.description)
    logger.info(f"Saved job: {job.title} at {job.company}")
    return "Job saved"


@tools.action("Read all saved jobs from CSV")
def read_saved_jobs() -> str:
    """Return the contents of the jobs CSV for later inspection."""
    if not JOBS_CSV.exists():
        return "No jobs have been saved yet."
    with JOBS_CSV.open() as f:
        return f.read()


# ---------------------------------------------------------------------------
# Agent Task Construction
# ---------------------------------------------------------------------------

def build_task_prompt(role: str) -> str:
    """Construct a natural language prompt instructing the agent to search for jobs.

    This prompt directs the agent to use Seek, Indeed, and LinkedIn to
    gather job postings in Melbourne for a given role.  It reminds the
    agent to record only the job title, company, description,
    requirements, and salary, and to use the ``save_job`` action for
    each posting.  The agent should ignore roles outside of Melbourne and
    stop after collecting a reasonable number of postings (e.g. 30).

    Args:
        role: The job title or keyword to search for.

    Returns:
        A multi‑line string ready to pass into the ``Agent`` initializer.
    """
    return (
        f"You are a job research assistant. Search for '{role}' roles in Melbourne, Victoria, Australia on "
        "Seek, Indeed, and LinkedIn. For each unique job posting you find, extract the following fields: "
        "job title, company name, job description, job requirements, and salary (if listed). After extracting "
        "these details, call the 'save_job' tool with a Job object containing those fields. Avoid saving "
        "duplicate postings: if a job description looks the same as one you've already saved, skip it. "
        "Do not apply for jobs; simply collect and record the data. Once you have gathered around 30 postings "
        "or there are no more relevant listings, stop."
    )


async def run_agents_sequentially() -> None:
    """Run one agent per role sequentially to avoid overwhelming resources."""
    model = ChatOpenAI(model="gpt-4.1-mini")
    for role in ROLE_LIST:
        prompt = build_task_prompt(role)
        agent = Agent(task=prompt, llm=model, tools=tools)
        logger.info(f"Starting job search for role: {role}")
        await agent.run()
        logger.info(f"Completed job search for role: {role}")


def main() -> None:
    """Entry point for synchronous execution."""
    asyncio.run(run_agents_sequentially())


if __name__ == "__main__":
    main()