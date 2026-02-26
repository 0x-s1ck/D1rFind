import requests
from requests.adapters import HTTPAdapter
from urllib.parse import urlparse
import random, time, threading, sys
from datetime import datetime
from queue import Queue

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"

MAX_WORKERS = 40
TIMEOUT = 4
DELAY_MIN = 0.01
DELAY_MAX = 0.03
MAX_DEPTH = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Mozilla/5.0 (X11; Linux x86_64)",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
    "Mozilla/5.0 (Android 11; Mobile)"
]

ADMIN_PATHS = [
    "admin","administrator","cpanel","phpmyadmin",
    "panel","backend","manage","dashboard","control",
    "api","api/v1","api/v2","api/admin","graphql","rest",
    "login","signin","auth","account","user","users",
    "config","configuration","settings","configs",
    "test","staging","dev","v2","v1"
]

UPLOAD_PATHS = [
    "upload","uploads","files","file","assets","media",
    "images","img","storage","storage/app","tmp","cache",
    "adminpanel","admin-panel","admin_area","adminarea",
    "backoffice","controlpanel","cp",
    "userfiles","private","protected",
    "backup","backups","old","archive",
    "testing"
]

COMMON_PATHS = [
    "backup","db","uploads/backup","storage","files/backup","data","archive","resources"
]

SUB_PATHS = [
    "assets","files","images","img","media","uploads",
    "backup","backups","data","storage","static","cdn",
    "content","downloads","documents","photos","pictures"
]

def generate_folder_paths(domain):
    clean = domain.replace("www.", "")
    parts = clean.split(".")
    sld = {"co.id","ac.id","sch.id","go.id","or.id","web.id","my.id"}
    last_two = ".".join(parts[-2:])
    if last_two in sld and len(parts) >= 3:
        main = parts[-3]
    elif len(parts) >= 2:
        main = parts[-2]
    else:
        main = parts[0]

    out = set()
    
    out.update(ADMIN_PATHS)
    out.update(UPLOAD_PATHS)
    out.update(COMMON_PATHS)
    out.add(main)
    
    for admin in ADMIN_PATHS:
        for sub in SUB_PATHS:
            out.add(f"{admin}/{sub}")
        for up in UPLOAD_PATHS:
            out.add(f"{admin}/{up}")
    
    for up in UPLOAD_PATHS:
        for sub in SUB_PATHS:
            out.add(f"{up}/{sub}")
        for up2 in UPLOAD_PATHS:
            out.add(f"{up}/{up2}")
    
    for cp in COMMON_PATHS:
        for sub in SUB_PATHS:
            out.add(f"{cp}/{sub}")
    
    return out

def headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Connection": "keep-alive"
    }

def ensure_https(url):
    url = url.strip().replace("http://","").replace("https://","")
    return f"https://{url.rstrip('/')}"

def check_folder(url, depth=0, session=None):
    if session is None:
        session = requests.Session()
        adapter = HTTPAdapter(max_retries=2, pool_connections=20, pool_maxsize=20)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(headers())
    
    for attempt in range(3):
        try:
            resp = session.get(url, timeout=TIMEOUT, allow_redirects=True, verify=False)
            
            final_url = resp.url.rstrip('/')
            original_url = url.rstrip('/')
            
            if final_url != original_url:
                return {"status": "MISS", "url": url, "redirect": final_url, "depth": depth}
            
            if resp.status_code != 200:
                return {"status": "MISS", "url": url, "depth": depth}
            
            ctype = resp.headers.get('Content-Type', '').lower()
            body = resp.text.lower()
            
            if len(resp.text) < 10:
                return {"status": "MISS", "url": url, "depth": depth}
            
            is_html = 'html' in ctype
            
            index_patterns = [
                'index of /', '[to parent directory]', '[directory]',
                '<title>index of', '<h1>index of', '<h1>directory'
            ]
            
            if is_html:
                found_patterns = [p for p in index_patterns if p in body]
                if found_patterns:
                    return {"status": "FOUND", "url": url, "patterns": found_patterns, "depth": depth}
            
            if not is_html:
                if any(x in body for x in ['404', 'error 404', 'page not found', 'file not found', 'does not exist', 'could not be found', 'not found']):
                    return {"status": "MISS", "url": url, "depth": depth}
                return {"status": "FOUND", "url": url, "content_type": ctype, "depth": depth}
            
            import re
            
            text_only = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL)
            text_only = re.sub(r'<style[^>]*>.*?</style>', '', text_only, flags=re.DOTALL)
            text_only = re.sub(r'<[^>]+>', '', text_only)
            text_only = re.sub(r'&[a-z]+;', ' ', text_only)
            text_stripped = text_only.strip()
            words = text_stripped.split()
            alpha_words = [w for w in words if re.search(r'[a-zA-Z]{3,}', w)]
            
            if len(words) < 10:
                return {"status": "MISS", "url": url, "depth": depth}
            
            if len(alpha_words) < 5:
                return {"status": "MISS", "url": url, "depth": depth}
            
            if len(text_stripped) < 100:
                return {"status": "MISS", "url": url, "depth": depth}
            
            if len(text_stripped) < 500 and any(x in body for x in ['please wait', 'checking your browser', 'one moment']):
                if attempt < 2:
                    time.sleep(2)
                    continue
                return {"status": "CLOUDFLARE", "url": url, "depth": depth}
            
            redirect_keywords = [
                'login', 'signin', 'password', 'access denied',
                'forbidden', 'rejected', 'blocked', 'suspended',
                'banned', 'cloudflare', 'captcha',
                'too many requests', 'rate limit'
            ]
            if any(x in body for x in redirect_keywords):
                return {"status": "MISS", "url": url, "depth": depth}
            
            url_lower = url.lower()
            is_404_file = url_lower.endswith('/404') or '/404.' in url_lower or url_lower.endswith('404.php') or url_lower.endswith('404.html') or url_lower.endswith('404.htm')
            
            if not is_404_file:
                error_404_phrases = ['404', 'error 404', 'page not found', 'file not found', 'does not exist', 'could not be found']
                if any(x in body for x in error_404_phrases):
                    return {"status": "MISS", "url": url, "depth": depth}
            
            return {"status": "MISS", "url": url, "depth": depth}
            
        except Exception as e:
            return {"status": "ERROR", "url": url, "depth": depth}

def generate_subpaths(base_url):
    subpaths = []
    for sub in SUB_PATHS:
        subpaths.append(f"{base_url}/{sub}")
    for up in UPLOAD_PATHS:
        subpaths.append(f"{base_url}/{up}")
    for cp in COMMON_PATHS:
        subpaths.append(f"{base_url}/{cp}")
    return subpaths

def worker(q, results, lock, processed, consecutive_errors, error_lock, should_stop, recursive_enabled, visited, error_limit=80):
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=2, pool_connections=20, pool_maxsize=20)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(headers())
    
    while True:
        if should_stop[0]:
            break
        
        try:
            item = q.get_nowait()
        except:
            break
            
        if item is None:
            break
        
        if isinstance(item, tuple):
            url, depth = item
        else:
            url = item
            depth = 0
        
        with lock:
            if url in visited:
                q.task_done()
                continue
            visited.add(url)
        
        result = check_folder(url, depth, session)
        status = result.get("status", "UNKNOWN")
        
        with error_lock:
            if status == "ERROR":
                consecutive_errors[0] += 1
                if consecutive_errors[0] >= error_limit:
                    should_stop[0] = True
            else:
                consecutive_errors[0] = 0
        
        if should_stop[0]:
            q.task_done()
            for _ in range(MAX_WORKERS):
                try:
                    q.put_nowait(None)
                except:
                    pass
            break
        
        if status == "FOUND":
            content_type = result.get("content_type", "")
            if content_type and 'html' not in content_type:
                print(f"{GREEN}[FOUND]{RESET} {url} ({content_type}) (depth:{depth})", flush=True)
            else:
                print(f"{GREEN}[FOUND]{RESET} {url} (depth:{depth})", flush=True)
            
            if recursive_enabled and depth < MAX_DEPTH:
                new_depth = depth + 1
                subpaths = generate_subpaths(url.rstrip('/'))
                for sp in subpaths:
                    try:
                        q.put_nowait((sp, new_depth))
                    except:
                        pass
        elif status == "MISS":
            print(f"{RED}[MISS]{RESET} {url}", flush=True)
        
        with lock:
            processed[0] += 1
        
        results.append(result)
        q.task_done()

def progress_thread(processed, total, lock):
    spinner = ["0", "x", "+", "-", "/", "\\", "*", "o", "O", "@", "#", "%", "=", ":", ".", "~"]
    idx = 0
    while True:
        with lock:
            done = processed[0]
        
        if done >= total:
            print(file=sys.stderr)
            break
        
        spin = spinner[idx % len(spinner)]
        idx += 1
        print(f"{spin}", end="\r", flush=True, file=sys.stderr)
        time.sleep(0.2)

requests.packages.urllib3.disable_warnings()

print("\n[1] Mass Scan (file)")
print("[2] Single Target\n")
mode = input("Pilih Mode : ").strip()

print("\n[1] Normal Scan")
print(f"[2] Recursive Scan (max depth: {MAX_DEPTH})\n")
recursive_mode = input("Pilih Mode Scan : ").strip()
recursive_enabled = recursive_mode == "2"

targets = []
if mode == "1":
    fname = input("Nama file : ").strip()
    with open(fname) as f:
        targets = [ensure_https(x.strip()) for x in f if x.strip()]
elif mode == "2":
    targets.append(ensure_https(input("Target domain: ").strip()))
else:
    exit()

for target in targets:
    domain = urlparse(target).netloc
    print(f"\nTARGET → {domain}\n")
    
    folders = list(generate_folder_paths(domain))
    urls = [f"{target}/{f}" for f in folders]
    
    q = Queue()
    results = []
    
    for u in urls:
        q.put(u)
    
    lock = threading.Lock()
    processed = [0]
    total = len(urls)
    consecutive_errors = [0]
    error_lock = threading.Lock()
    visited = set()
    
    should_stop = [False]
    threads = []
    for _ in range(MAX_WORKERS):
        t = threading.Thread(target=worker, args=(q, results, lock, processed, consecutive_errors, error_lock, should_stop, recursive_enabled, visited))
        t.start()
        threads.append(t)
    
    p = threading.Thread(target=progress_thread, args=(processed, total, lock))
    p.start()
    
    skipped = False
    while True:
        if should_stop[0] or consecutive_errors[0] >= 80:
            with q.mutex:
                q.queue.clear()
            with lock:
                processed[0] = total
            print(f"{RED}[SKIP]{RESET} {domain} skipped (too many errors)\n")
            skipped = True
            break
        if q.empty():
            break
        time.sleep(0.02)
    
    if skipped:
        for _ in threads:
            try:
                q.put_nowait(None)
            except:
                pass
        for t in threads:
            t.join(timeout=0.5)
        p.join(timeout=0.5)
        continue

    for _ in threads:
        q.put(None)
    for t in threads:
        t.join(timeout=1)
    p.join(timeout=0.5)
    
    found = [r["url"] for r in results if r["status"] == "FOUND"]
    cloudflare = [r["url"] for r in results if r["status"] == "CLOUDFLARE"]
    
    if found:
        import os
        clean = domain.replace("www.", "")
        parts = clean.split(".")
        sld = {"co.id","ac.id","sch.id","go.id","or.id","web.id","my.id"}
        last_two = ".".join(parts[-2:])
        if last_two in sld and len(parts) >= 3:
            folder_name = parts[-3]
        elif len(parts) >= 2:
            folder_name = parts[-2]
        else:
            folder_name = parts[0]
        
        base_folder = folder_name
        suffix = ".result"
        counter = 0
        
        while os.path.isfile(base_folder):
            counter += 1
            base_folder = f"{folder_name}{suffix}{counter}"
        
        os.makedirs(base_folder, exist_ok=True)
        with open(f"{base_folder}/{domain}.txt", "w") as f:
            for x in found:
                f.write(x + "\n")
    
    print("\nSTATUS SUMMARY")
    print(f"Total Checked : {len(results)}")
    print(f"Found         : {len(found)}")
    print(f"Cloudflare    : {len(cloudflare)}\n")
