# 📚 만화 베스트셀러 · 굿즈 현황

예스24 · 알라딘 · 교보문고 만화/라이트노벨 베스트셀러 + 굿즈 자동 수집

## 작동 방식

```
GitHub Actions (매시간 자동)
    ↓
collector.py (Playwright로 3서점 크롤링)
    ↓
history.json + CSV 저장 → git push
    ↓
GitHub Pages (index.html이 history.json 읽어서 렌더링)
```

## 파일 구조

| 파일 | 역할 |
|---|---|
| `collector.py` | 3서점 크롤러 (굿즈·이벤트 포함) |
| `.github/workflows/collect.yml` | 매시간 자동 실행 |
| `index.html` | 대시보드 (GitHub Pages) |
| `history.json` | 수집 이력 (자동 누적) |
| `*_manga.csv` | 서점별 최신 데이터 |

## GitHub Pages 활성화

1. 저장소 → **Settings** → **Pages**
2. Source: **Deploy from a branch**
3. Branch: **main** / **/ (root)**
4. Save

주소: `https://down-cyber.github.io/manga-bestseller/`
