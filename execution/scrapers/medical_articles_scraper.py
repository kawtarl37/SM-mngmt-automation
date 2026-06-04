import requests
import xml.etree.ElementTree as ET
import time
from execution.db import get_connection
from execution.utils.logger import setup_logger

logger = setup_logger("medical_articles_scraper")

def fetch_medical_article_ids(limit: int = 10) -> list:
    """Search PubMed for recent articles on celiac disease or gluten-free diets."""
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    params = {
        "db": "pubmed",
        "term": "celiac disease[Title/Abstract] OR gluten-free[Title/Abstract]",
        "retmode": "json",
        "sort": "pub_date",
        "retmax": limit
    }
    headers = {
        "User-Agent": "EGF-Automation/1.0 (Contact: user@easygluten-free.com)"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        logger.info(f"PubMed search returned {len(ids)} article IDs.")
        return ids
    except Exception as e:
        logger.error(f"Failed to fetch PubMed article IDs: {e}")
        return []

def fetch_article_details(pmids: list) -> str:
    """Fetch XML metadata (titles, journals, abstracts) for a list of PubMed IDs."""
    if not pmids:
        return ""
    
    url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml"
    }
    headers = {
        "User-Agent": "EGF-Automation/1.0 (Contact: user@easygluten-free.com)"
    }

    try:
        response = requests.get(url, params=params, headers=headers, timeout=20)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.error(f"Failed to fetch PubMed article details: {e}")
        return ""

def parse_and_save_articles(xml_data: str) -> int:
    """Parse PubMed efetch XML and save articles to trend_topics table."""
    if not xml_data:
        return 0

    try:
        root = ET.fromstring(xml_data.encode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to parse XML data: {e}")
        return 0

    saved_count = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        
        for article in root.findall('.//PubmedArticle'):
            try:
                # Extract title
                title_el = article.find('.//ArticleTitle')
                if title_el is None:
                    continue
                title = "".join(title_el.itertext()).strip()
                # Clean title trailing dot if any
                if title.endswith("."):
                    title = title[:-1]

                # Extract journal title
                journal_el = article.find('.//Journal/Title')
                journal = "".join(journal_el.itertext()).strip() if journal_el is not None else "PubMed Medical Journal"

                # Extract abstract
                abstract_texts = article.findall('.//AbstractText')
                abstract = ""
                if abstract_texts:
                    abstract = " ".join("".join(el.itertext()).strip() for el in abstract_texts)
                
                if not abstract:
                    abstract = f"Medical research article published in {journal}."

                # Check if already exists in trend_topics to avoid duplicates
                cursor.execute("SELECT 1 FROM trend_topics WHERE title = ? AND source = 'medical_article'", (title,))
                if cursor.fetchone():
                    continue

                # Insert with high score (300) so they rank highly in trend_analyzer
                cursor.execute(
                    """INSERT INTO trend_topics
                       (source, subreddit, title, body, score, comment_count)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        "medical_article",
                        journal, # Store journal in subreddit column
                        title,
                        abstract,
                        300, # Mock high score for relevance ranking
                        0
                    )
                )
                saved_count += 1
            except Exception as ex:
                logger.warning(f"Error parsing individual PubMed article: {ex}")
                continue
                
        conn.commit()
    return saved_count

def run_scraper(limit: int = 10) -> int:
    """Main entrypoint for medical articles scraper."""
    logger.info("Starting PubMed medical articles scraper...")
    pmids = fetch_medical_article_ids(limit)
    if not pmids:
        logger.warning("No articles found to fetch.")
        return 0
        
    # Be polite to the public NCBI API
    time.sleep(1)
    
    xml_data = fetch_article_details(pmids)
    new_saved = parse_and_save_articles(xml_data)
    logger.info(f"Medical articles scraper completed. Newly saved articles: {new_saved}")
    return new_saved

if __name__ == "__main__":
    run_scraper()
