 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app/config.py b/app/config.py
index 085695cded2632071089fa5d767410ca315bd608..de57cd697ef9aca648cbb74b83c27d7ae7ddd0c0 100644
--- a/app/config.py
+++ b/app/config.py
@@ -1,33 +1,41 @@
+import logging
 import os
 from pathlib import Path
+
 from dotenv import load_dotenv
 
 # .env را از ریشه پروژه بخوان (کنار پوشه app)
 load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")
 
 BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
 
 _raw = os.getenv("OWNER_IDS", "").strip()
 OWNER_IDS: set[int] = set()
 
 if _raw:
     for x in _raw.split(","):
         x = x.strip()
         if x.isdigit():
             OWNER_IDS.add(int(x))
 else:
     one = os.getenv("OWNER_ID", "").strip()
     if one.isdigit():
         OWNER_IDS.add(int(one))
 
 PRIMARY_OWNER_ID = next(iter(OWNER_IDS), 0)
-
-print("DEBUG CONFIG -> BOT_TOKEN set:", bool(BOT_TOKEN))
-print("DEBUG CONFIG -> OWNER_IDS:", OWNER_IDS)
-print("DEBUG CONFIG -> PRIMARY_OWNER_ID:", PRIMARY_OWNER_ID)
+_DEBUG = os.getenv("ECLIS_DEBUG", "").lower() in {"1", "true", "yes"} or os.getenv("DEBUG", "").lower() in {
+    "1",
+    "true",
+    "yes",
+}
+_logger = logging.getLogger("eclis.config")
+if _DEBUG:
+    _logger.debug("DEBUG CONFIG -> BOT_TOKEN set: %s", bool(BOT_TOKEN))
+    _logger.debug("DEBUG CONFIG -> OWNER_IDS: %s", OWNER_IDS)
+    _logger.debug("DEBUG CONFIG -> PRIMARY_OWNER_ID: %s", PRIMARY_OWNER_ID)
 
 def is_owner(user_id: int) -> bool:
     return int(user_id) in OWNER_IDS
 
 # سازگاری عقب‌رو (اگر جایی هنوز OWNER_ID می‌خواهد)
 OWNER_ID = PRIMARY_OWNER_ID
 
EOF
)
