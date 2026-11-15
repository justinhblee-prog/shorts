"""Ten-brand operating registry for NEXUS STUDIO PRO."""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone


DEFAULT_BRANDS = [
    {"slug":"brain-glitch","name":"Brain Glitch","vertical":"neuroscience_psychology",
     "positioning":"Evidence-led explanations of brain and behavior","audience":"curious general audience",
     "tone":["curious","clear","evidence-led"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"elevated","keywords":["neuroscience","psychology","brain","memory","attention","cognitive science","behavior"],"review_rules":["Cite credible sources for scientific claims","Do not diagnose viewers"]},
    {"slug":"silent-signals","name":"Silent Signals","vertical":"relationships_nonverbal",
     "positioning":"Practical insight into relationships and nonverbal communication","audience":"general adult audience",
     "tone":["empathetic","observant","nonjudgmental"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"standard","keywords":["relationships","communication","body language","nonverbal","social cues","dating","interpersonal"],"review_rules":["Avoid manipulative relationship advice","Distinguish research from opinion"]},
    {"slug":"unseen-truth","name":"Unseen Truth","vertical":"history_context",
     "positioning":"Hidden context behind historical events","audience":"history-curious viewers",
     "tone":["documentary","intriguing","balanced"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"elevated","keywords":["history","historical events","archaeology","ancient civilizations","primary sources","historical context"],"review_rules":["Verify dates and primary-source claims","Separate disputed interpretations from established facts"]},
    {"slug":"dark-files-global","name":"Dark Files Global","vertical":"space_ocean_mysteries",
     "positioning":"Documented mysteries of space and the deep sea","audience":"science and mystery enthusiasts",
     "tone":["cinematic","curious","skeptical"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"elevated","keywords":["space","astronomy","deep sea","ocean","astrophysics","marine science","exploration","documented mysteries"],"review_rules":["No fabricated discoveries or conspiracy claims","Label hypotheses and unknowns clearly"]},
    {"slug":"99-missed","name":"99% Missed","vertical":"everyday_knowledge_productivity",
     "positioning":"Useful overlooked facts and practical productivity","audience":"broad general audience",
     "tone":["useful","fast","friendly"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"standard","keywords":["productivity","everyday knowledge","practical science","learning","habits","time management","useful facts"],"review_rules":["Check practical advice for context and limitations"]},
    {"slug":"money-glitch","name":"Money Glitch","vertical":"economics_finance",
     "positioning":"Explain economic mechanisms and financial literacy","audience":"financially curious adults",
     "tone":["analytical","plainspoken","cautious"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"high","keywords":["economics","finance","inflation","financial literacy","markets","monetary policy","personal finance"],"review_rules":["No personalized investment recommendations","Date and source all market data","Clearly label opinion and forecasts"]},
    {"slug":"secret-vault-24","name":"Secret Vault 24","vertical":"corporate_economic_secrets",
     "positioning":"Investigative explainers on corporate and economic stories","audience":"business-curious viewers",
     "tone":["investigative","precise","skeptical"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"high","keywords":["corporate","business","companies","corporate history","mergers","regulation","economic stories"],"review_rules":["Substantiate allegations with reliable public evidence","Avoid defamatory claims and misleading insinuation"]},
    {"slug":"future-leak","name":"Future Leak","vertical":"ai_future_technology",
     "positioning":"Accessible analysis of AI and emerging technology","audience":"technology-curious viewers",
     "tone":["forward-looking","clear","grounded"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"elevated","keywords":["artificial intelligence","AI","machine learning","robotics","emerging technology","software","computing"],"review_rules":["Distinguish shipped capabilities from demos and speculation","Date fast-changing claims"]},
    {"slug":"30sec-shift","name":"30Sec Shift","vertical":"health_sleep_longevity",
     "positioning":"Evidence-aware health, sleep and longevity explainers","audience":"general wellness audience",
     "tone":["reassuring","practical","evidence-led"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"high","keywords":["health","sleep","longevity","nutrition","exercise","public health","wellness","clinical research"],"review_rules":["No diagnosis or treatment claims","Use authoritative health sources","Flag uncertainty and consult-professional boundaries"]},
    {"slug":"why-nobody-tells","name":"Why Nobody Tells","vertical":"social_business_insights",
     "positioning":"Explain overlooked social and business dynamics","audience":"curious working adults",
     "tone":["direct","insightful","balanced"],"regions":["KR","US","JP","GB"],"languages":["ko","en","ja"],
     "risk_level":"standard","keywords":["social dynamics","workplace","business","organizational behavior","incentives","culture","social insights"],"review_rules":["Avoid presenting anecdotes as universal truths","Attribute disputed claims"]},
]


def now():
    return datetime.now(timezone.utc).isoformat()


class BrandNotFound(KeyError):
    pass


class BrandStore:
    def __init__(self, db_path="data/nexus.sqlite3"):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.db() as c:
            c.execute("""CREATE TABLE IF NOT EXISTS brand_profiles(
              slug TEXT PRIMARY KEY, name TEXT NOT NULL, vertical TEXT NOT NULL,
              config_json TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL)""")
        self.seed_defaults()

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.db_path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=30000")
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise
        finally:
            c.close()

    def seed_defaults(self):
        with self.db() as c:
            for brand in DEFAULT_BRANDS:
                c.execute("""INSERT OR IGNORE INTO brand_profiles
                  (slug,name,vertical,config_json,active,created_at,updated_at)
                  VALUES(?,?,?,?,1,?,?)""",
                  (brand["slug"],brand["name"],brand["vertical"],
                   json.dumps(brand,ensure_ascii=False),now(),now()))
                # Add newly introduced default taxonomy fields to existing rows
                # without overwriting operator-customized brand settings.
                row = c.execute(
                    "SELECT config_json FROM brand_profiles WHERE slug=?",
                    (brand["slug"],)
                ).fetchone()
                existing = json.loads(row["config_json"])
                changed = False
                for key in ("keywords", "exclude_keywords"):
                    if key not in existing and key in brand:
                        existing[key] = brand[key]
                        changed = True
                if changed:
                    c.execute(
                        "UPDATE brand_profiles SET config_json=?,updated_at=? WHERE slug=?",
                        (json.dumps(existing, ensure_ascii=False), now(), brand["slug"])
                    )

    def list(self, active_only=False):
        query = "SELECT * FROM brand_profiles"
        if active_only:
            query += " WHERE active=1"
        query += " ORDER BY name"
        with self.db() as c:
            return [self._decode(row) for row in c.execute(query)]

    def get(self, slug):
        with self.db() as c:
            row = c.execute("SELECT * FROM brand_profiles WHERE slug=?", (slug,)).fetchone()
            return self._decode(row) if row else None

    def set_active(self, slug, active):
        with self.db() as c:
            cur = c.execute("UPDATE brand_profiles SET active=?,updated_at=? WHERE slug=?",
                            (1 if active else 0,now(),slug))
            if cur.rowcount == 0:
                raise BrandNotFound(slug)
        return self.get(slug)

    @staticmethod
    def _decode(row):
        if row is None:
            return None
        result = dict(row)
        result["config"] = json.loads(result.pop("config_json"))
        result["active"] = bool(result["active"])
        return result
