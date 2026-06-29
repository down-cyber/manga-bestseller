import csv, json, time, re
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("playwright 없음: pip install playwright")
    exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("beautifulsoup4 없음: pip install beautifulsoup4")
    exit(1)

KST = timezone(timedelta(hours=9))
HISTORY_FILE = "history.json"
STORES = ["yes24", "aladin", "kyobo"]
FIELDNAMES = ["수집시각", "순위", "제목", "저자", "출판사", "굿즈", "이벤트", "링크", "이미지URL", "이전순위", "순위변동"]

# ────────────────────────────────────────────
# 브라우저 공통
# ────────────────────────────────────────────
def fetch_html(url, wait_ms=4000):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page = ctx.new_page()
        page.goto(url, timeout=30000)
        page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()
    return html

def fetch_html_with_page(url, wait_ms=3500):
    """페이지 객체를 반환 (교보 상세용)"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page = ctx.new_page()
        page.goto(url, timeout=30000)
        page.wait_for_timeout(wait_ms)
        html = page.content()
        browser.close()
    return html

# ────────────────────────────────────────────
# 굿즈 파싱 헬퍼
# ────────────────────────────────────────────
def parse_goods_from_title(title_raw):
    """제목에서 굿즈 정보 추출
    예) "원피스 114 - 띠지 + 초판한정 일러스트 카드 1종" → ["띠지", "초판한정 일러스트 카드 1종"]
    """
    dash = title_raw.find(' - ')
    if dash == -1:
        return []
    after = title_raw[dash + 3:]
    parts = [p.strip() for p in re.split(r'\s*\+\s*|\s*,\s*', after) if p.strip()]
    return [p for p in parts if 2 < len(p) < 80]

def categorize(text):
    t = text.lower()
    if any(k in t for k in ['한정', '특전', '초판', '단독']):
        return 'limit'
    if any(k in t for k in ['이벤트', '사은품', '증정', '출간 기념']):
        return 'event'
    return 'goods'

# ────────────────────────────────────────────
# 예스24 만화 베스트
# ────────────────────────────────────────────
YES24_URL = "https://www.yes24.com/product/category/bestseller?categoryNumber=001001008"

def parse_yes24(html, now):
    soup = BeautifulSoup(html, "html.parser")
    books = []
    seen = set()
    for item in soup.select('.itemUnit'):
        title_a = item.select_one('a.gd_name')
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        if title in seen:
            continue
        seen.add(title)

        rank = str(len(books) + 1)
        link = title_a.get('href', '')
        if link and not link.startswith('http'):
            link = 'https://www.yes24.com' + link

        # 저자/출판사
        auth_span = item.select_one('.info_auth')
        raw_auth = auth_span.get_text(separator=' ', strip=True) if auth_span else ''
        author = re.sub(r'\s*(저|역|글|그림|편)\s*$', '', raw_auth.split('/')[0]).strip()
        pub_span = item.select_one('.info_pub')
        publisher = pub_span.get_text(strip=True) if pub_span else ''

        # 굿즈: 구매혜택 텍스트에서
        full_text = item.get_text()
        goods_match = re.search(r'구매혜택\s*([^\n]+)', full_text)
        goods_raw = ''
        if goods_match:
            goods_raw = re.sub(r'\[단독\]|\[YES단독\]|\[예스단독\]', '', goods_match.group(1))
            goods_raw = re.sub(r'\(포인트[^)]*\)|\(포함[^)]*\)', '', goods_raw).strip()

        # 이미지
        goods_id = link.split('/')[-1].split('?')[0] if link else ''
        img_url = f"https://image.yes24.com/goods/{goods_id}/XL" if goods_id else ''

        books.append({
            "수집시각": now, "순위": rank,
            "제목": title, "저자": author, "출판사": publisher,
            "굿즈": goods_raw, "이벤트": "",
            "링크": link, "이미지URL": img_url,
            "이전순위": "", "순위변동": ""
        })
        if len(books) >= 30:
            break
    return books

def scrape_yes24(now):
    print("  예스24 수집 중...")
    html = fetch_html(YES24_URL)
    books = parse_yes24(html, now)
    print(f"  예스24 {len(books)}권")
    return books

# ────────────────────────────────────────────
# 알라딘 만화 베스트
# ────────────────────────────────────────────
ALADIN_URL = "https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&CID=2551&page=1&view=list"

def parse_aladin(html, now):
    soup = BeautifulSoup(html, "html.parser")
    books = []
    seen_hrefs = set()
    rank = 0

    for a in soup.find_all('a'):
        href = a.get('href', '')
        if 'ItemId' not in href and 'wproduct' not in href:
            continue
        cls = a.get('class', [])
        if 'ico_nWin' in cls:
            continue
        title_raw = a.get_text(strip=True)
        if not title_raw or len(title_raw) < 3 or len(title_raw) > 120:
            continue
        if href in seen_hrefs:
            continue
        seen_hrefs.add(href)
        rank += 1

        # 제목에서 굿즈 분리 (알라딘은 제목 자체에 포함)
        clean_title = re.sub(r'\[국내도서\]', '', title_raw).strip()
        title = clean_title.split(' - ')[0].strip()
        goods_from_title = ' + '.join(parse_goods_from_title(clean_title))

        # 부모에서 출판사
        parent = a.find_parent('td') or a.find_parent('tr') or a.find_parent('li') or a.parent
        parent_text = parent.get_text(strip=True) if parent else ''
        pub_m = re.search(r'\|\s*([가-힣a-zA-Z\(\)]+(?:만화|미디어|문화사|문고|동네|북스)?)\s*\|\s*\d{4}년', parent_text)
        publisher = pub_m.group(1).strip() if pub_m else ''

        # 굿즈 배너 (ss_ht1)
        ht1 = parent.find(class_='ss_ht1') if parent else None
        goods_banner = ht1.get_text(strip=True) if ht1 else ''

        goods_final = goods_from_title or goods_banner

        books.append({
            "수집시각": now, "순위": str(rank),
            "제목": title, "저자": "", "출판사": publisher,
            "굿즈": goods_final, "이벤트": "",
            "링크": 'https://www.aladin.co.kr' + href if href.startswith('/') else href,
            "이미지URL": "",
            "이전순위": "", "순위변동": ""
        })
        if rank >= 30:
            break
    return books

def scrape_aladin(now):
    print("  알라딘 수집 중...")
    html = fetch_html(ALADIN_URL)
    books = parse_aladin(html, now)
    print(f"  알라딘 {len(books)}권")
    return books

# ────────────────────────────────────────────
# 교보문고 만화 베스트 (Playwright 탭 클릭 방식)
# ────────────────────────────────────────────
KYOBO_BASE = "https://store.kyobobook.co.kr/bestseller/online/daily"

def scrape_kyobo(now):
    """
    교보문고는 Next.js SPA라 URL 파라미터로 카테고리 필터가 안 됨.
    Playwright로 페이지를 열고 만화 카테고리 탭을 직접 클릭한 뒤 DOM을 파싱.
    """
    print("  교보문고 수집 중 (Playwright 탭 클릭 방식)...")
    books = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ))
        page = ctx.new_page()

        # 1) 베스트셀러 페이지 로드
        page.goto(KYOBO_BASE, timeout=30000)
        page.wait_for_timeout(4000)

        # 2) 만화 카테고리 탭 클릭
        # 카테고리 탭 텍스트가 "만화" 또는 "만화/라이트노벨"인 버튼/링크 클릭
        clicked = False
        for selector in [
            'button:has-text("만화")',
            'a:has-text("만화")',
            '[class*="tab"]:has-text("만화")',
            'li:has-text("만화")',
        ]:
            try:
                el = page.locator(selector).first
                if el.count() > 0:
                    el.click()
                    page.wait_for_timeout(3000)
                    clicked = True
                    print("    만화 탭 클릭 성공")
                    break
            except Exception:
                continue

        if not clicked:
            print("    만화 탭 클릭 실패 — 전체 베스트에서 만화 키워드 필터링")

        # 3) 필요시 더보기 클릭 (30권 확보)
        for _ in range(3):
            try:
                more_btn = page.locator('button:has-text("더보기"), button:has-text("더 보기")').first
                if more_btn.count() > 0:
                    more_btn.click()
                    page.wait_for_timeout(1500)
            except Exception:
                break

        # 4) DOM 파싱
        html = page.content()
        browser.close()

    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    rank = 0

    # 만화 관련 출판사 키워드 (탭 클릭 실패 시 필터로 사용)
    MANGA_PUB = {'대원씨아이', '대원', '학산문화사', '학산', '소미미디어',
                 '서울미디어코믹스', '디앤씨미디어', 'YNK미디어', '문학동네',
                 '시공사', '동학사', '애니북스', '길찾기', '대원'}

    for a in soup.find_all('a', href=True):
        href = a['href']
        if not re.search(r'product\.kyobobook\.co\.kr/detail/S\d+', href):
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 2 or title in ('새창보기', '미리보기', '') or len(title) > 100:
            continue
        if href in seen:
            continue

        parent = a.find_parent('li') or a.find_parent('tr') or a.parent
        parent_text = parent.get_text(strip=True) if parent else ''

        # 출판사 추출 (· 구분자)
        pub_m = re.search(r'·\s*([가-힣a-zA-Z\(\)]+(?:씨아이|미디어|문화사|문고|동네|북스|코믹스)?)\s*·', parent_text)
        publisher = pub_m.group(1).strip() if pub_m else ''

        # 탭 클릭 실패 시: 만화 출판사 필터 적용
        if not clicked and publisher and publisher not in MANGA_PUB:
            continue

        seen.add(href)
        rank += 1

        # 이미지 URL (ISBN 기반)
        isbn_m = re.search(r'(97[89]\d{10})', parent_text)
        img_url = f"https://contents.kyobobook.co.kr/sih/fit-in/458x0/pdt/{isbn_m.group(1)}.jpg" if isbn_m else ''

        books.append({
            "수집시각": now, "순위": str(rank),
            "제목": title, "저자": "", "출판사": publisher,
            "굿즈": "", "이벤트": "",
            "링크": href, "이미지URL": img_url,
            "이전순위": "", "순위변동": ""
        })
        if rank >= 30:
            break

    print(f"  교보문고 {len(books)}권 완료")
    return books

# ────────────────────────────────────────────
# 순위 변동 계산
# ────────────────────────────────────────────
def load_last_snapshot(store, current_hour=None):
    path = Path(HISTORY_FILE)
    if not path.exists():
        return {}
    with open(path, encoding='utf-8') as f:
        history = json.load(f)
    if not history:
        return {}
    last_entry = None
    for entry in reversed(history):
        if current_hour and entry.get('수집시각', '')[:13] == current_hour:
            continue
        last_entry = entry
        break
    if not last_entry:
        return {}
    store_data = last_entry.get('데이터', {}).get(store, [])
    return {row['제목']: row['순위'] for row in store_data if isinstance(row, dict)}

def calc_change(current, previous):
    if not previous:
        return "NEW"
    try:
        diff = int(previous) - int(current)
        if diff > 0:   return f"↑{diff}"
        elif diff < 0: return f"↓{abs(diff)}"
        else:          return "–"
    except ValueError:
        return "–"

# ────────────────────────────────────────────
# 저장
# ────────────────────────────────────────────
def save_csv(store, books):
    path = Path(f"{store}_manga.csv")
    with open(path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(books)
    print(f"  {path} 저장 ({len(books)}권)")

def save_history(all_books, now):
    path = Path(HISTORY_FILE)
    history = []
    if path.exists():
        with open(path, encoding='utf-8') as f:
            try:
                history = json.load(f)
            except Exception:
                history = []
    current_hour = now[:13]
    replaced = False
    for i, entry in enumerate(history):
        if entry.get('수집시각', '')[:13] == current_hour:
            history[i] = {"수집시각": now, "데이터": all_books}
            replaced = True
            break
    if not replaced:
        history.append({"수집시각": now, "데이터": all_books})
    history = history[-60:]  # 최근 60회 유지
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"  history.json 저장 (총 {len(history)}회)")

# ────────────────────────────────────────────
# 메인
# ────────────────────────────────────────────
def main():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    print(f"\n[{now}] 만화 베스트셀러 수집 시작\n")

    current_hour = now[:13]
    all_books = {}

    # 수집
    all_books['yes24'] = scrape_yes24(now)
    all_books['aladin'] = scrape_aladin(now)
    all_books['kyobo'] = scrape_kyobo(now)

    # 순위 변동 계산
    for store, books in all_books.items():
        last = load_last_snapshot(store, current_hour)
        for book in books:
            prev = last.get(book['제목'], '')
            book['이전순위'] = prev
            book['순위변동'] = calc_change(book['순위'], prev)

    # 저장
    for store, books in all_books.items():
        if books:
            save_csv(store, books)
    save_history(all_books, now)

    print(f"\n수집 완료!")

if __name__ == "__main__":
    main()
