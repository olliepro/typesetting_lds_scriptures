from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from tqdm import tqdm

SCRAPER_REPO = "https://github.com/samuelbradshaw/python-scripture-scraper"
DEFAULT_CACHE = Path(".cache/scripture-scraper")


@dataclass
class ScraperConfig:
    include_copyrighted: bool = True
    include_images: bool = True
    pause_seconds: float = 0.25
    use_test_data: bool = False
    outputs: Iterable[str] = ("json", "html")


CONFIG_TEMPLATE = """# Auto-generated; do not edit by hand\n\nDEFAULT_LANG = 'en'\nSCRAPE_FULL_CONTENT = True\nSCRAPE_METADATA_FOR_ALL_LANGUAGES = False\nSECONDS_TO_PAUSE_BETWEEN_REQUESTS = {pause}\nJSON_INDENT = 2\nUSE_TEST_DATA = {use_test}\n\nif SCRAPE_FULL_CONTENT:\n  OUTPUT_AS_JSON = {json}\n  OUTPUT_AS_HTML = {html}\n  OUTPUT_AS_MD = {md}\n  OUTPUT_AS_TXT = {txt}\n  OUTPUT_AS_CSV = {csv}\n  OUTPUT_AS_TSV = {tsv}\n  OUTPUT_AS_SQL_MYSQL = {mysql}\n  OUTPUT_AS_SQL_SQLITE = {sqlite}\n  SPLIT_JSON_BY_CHAPTER = True\n  MINIFY_JSON = False\n  BASIC_HTML = False\n  INCLUDE_IMAGES = {images}\n  INCLUDE_COPYRIGHTED_CONTENT = {copyrighted}\n  INCLUDE_MEDIA_INFO = False\n  ADD_CSS_STYLESHEET = True\n"""


def ensure_repo(path: Path = DEFAULT_CACHE) -> Path:
    """Clone the upstream scraper if it does not already exist."""
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", SCRAPER_REPO, str(path)], check=True)
    return path


def render_config(config: ScraperConfig) -> str:
    outputs = {k: False for k in ["json", "html", "md", "txt", "csv", "tsv", "mysql", "sqlite"]}
    for key in config.outputs:
        outputs[key] = True
    return CONFIG_TEMPLATE.format(
        pause=config.pause_seconds,
        use_test=str(config.use_test_data),
        images=str(config.include_images),
        copyrighted=str(config.include_copyrighted),
        **outputs,
    )


def write_config(repo_path: Path, config: ScraperConfig) -> Path:
    cfg_path = repo_path / "resources" / "config.py"
    cfg_path.write_text(render_config(config))
    return cfg_path


def run_scraper(output_dir: Path, config: ScraperConfig, repo_path: Path | None = None) -> Path:
    repo_path = ensure_repo(repo_path or DEFAULT_CACHE)
    write_config(repo_path, config)
    subprocess.run(["python", "-m", "pip", "install", "-r", "requirements.txt"], cwd=repo_path, check=True)
    subprocess.run(["python", "scrape.py"], cwd=repo_path, check=True)
    target = output_dir
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(repo_path / "_output", target)
    return target


def copy_sample(output_dir: Path, repo_path: Path | None = None) -> Path:
    repo_path = ensure_repo(repo_path or DEFAULT_CACHE)
    target = output_dir
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(repo_path / "sample", target)
    return target
