#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
lowprice_bot.py
다나와 가격비교(danawa-price-search 스킬 방식) 기반 물티슈 최저가 알림 봇

[핵심 요구사항]
1. '다나와' 검색 스킬 방식(dsearch.php + getAllPriceCompareMallList.ajax.php)으로 "베베앙 20개"를 최저가 순으로 검색
   (다나와 구형 UI `li.prod_item` 및 최신 개편 UI `li.border-b` / `data-product-seq` 모두 완벽 지원)
2. 최저가 순서로 상품 3개를 상품명, 가격, 쇼핑몰, 리뷰수, 링크와 함께 화면에 보기 좋게 출력
3. 반환된 광고 상품(AD/애드스마트/파워쇼핑/loadingBridgeAdSmart 등)은 제거하고, 실제 판매되는 상품만 필터링
4. 1위 가격의 목표가 20,000원 이하인지 확인 후 다음 중 하나를 함께 출력:
   - 목표가 이하일 때: "[특가발견] 목표가격이하입니다."
   - 목표가 초과일 때: "[유지] 아직 목표 가격보다 비싸요!"
5. 잘못된 값을 가져올 경우 지어내지 말고, 무엇이 잘못되었는지 그대로 알려주고 멈춤
"""

import argparse
from datetime import datetime
import html as html_lib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple


# Windows 콘솔 한글 깨짐 방지
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


DANAWA_SEARCH_URL = "https://search.danawa.com/dsearch.php"
DANAWA_MALL_AJAX_URL = "https://prod.danawa.com/info/ajax/getAllPriceCompareMallList.ajax.php"
KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_MEMO_SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

DEFAULT_ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://search.danawa.com/",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


class BotValidationError(Exception):
    """잘못된 값을 가져왔을 때 지어내지 않고 즉시 멈추기 위한 예외 클래스"""
    pass


class KakaoNotificationError(Exception):
    """카카오톡 알림 전송에 실패했을 때 보낸 척하지 않고 원인을 그대로 알리기 위한 예외 클래스"""
    pass


def load_env_file(env_path: str = DEFAULT_ENV_PATH) -> Dict[str, str]:
    """
    프로젝트 폴더의 .env 파일에서 환경변수를 읽어옵니다.
    키 값을 코드에 직접 하드코딩하지 않습니다.
    """
    if not os.path.exists(env_path):
        raise KakaoNotificationError(
            f"[인증 설정 오류] .env 파일을 찾을 수 없습니다 ({env_path})."
        )
    env_vars: Dict[str, str] = {}
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                env_vars[key.strip()] = val.strip().strip('"').strip("'")
    except Exception as e:
        raise KakaoNotificationError(
            f"[인증 설정 오류] .env 파일을 읽는 중 문제가 발생했습니다: {e}"
        ) from e
    return env_vars


def update_env_refresh_token(env_path: str, new_refresh_token: str) -> None:
    """카카오 토큰 갱신 시 새 refresh_token이 함께 반환되면 .env 파일에 업데이트합니다."""
    if not new_refresh_token or not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        updated = False
        new_lines = []
        for line in lines:
            if line.strip().startswith("KAKAO_REFRESH_TOKEN="):
                new_lines.append(f"KAKAO_REFRESH_TOKEN={new_refresh_token}\n")
                updated = True
            else:
                if not line.endswith("\n"):
                    line += "\n"
                new_lines.append(line)
        if not updated:
            new_lines.append(f"KAKAO_REFRESH_TOKEN={new_refresh_token}\n")
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception:
        pass


def get_kakao_access_token(env_path: str = DEFAULT_ENV_PATH) -> str:
    """
    .env 파일의 KAKAO_REST_API_KEY, KAKAO_CLIENT_SECRET, KAKAO_REFRESH_TOKEN을 사용해
    카카오 액세스 토큰을 갱신/발급받습니다.
    """
    env_vars = load_env_file(env_path)
    rest_api_key = env_vars.get("KAKAO_REST_API_KEY", "").strip()
    client_secret = env_vars.get("KAKAO_CLIENT_SECRET", "").strip()
    refresh_token = env_vars.get("KAKAO_REFRESH_TOKEN", "").strip()

    missing = []
    if not rest_api_key:
        missing.append("KAKAO_REST_API_KEY")
    if not client_secret:
        missing.append("KAKAO_CLIENT_SECRET")
    if not refresh_token:
        missing.append("KAKAO_REFRESH_TOKEN")

    if missing:
        raise KakaoNotificationError(
            f"[카카오 인증 정보 누락] .env 파일에 필수 항목이 없습니다: {', '.join(missing)}"
        )

    payload = {
        "grant_type": "refresh_token",
        "client_id": rest_api_key,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(
        KAKAO_TOKEN_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = getattr(resp, "status", 200)
            body = resp.read().decode("utf-8", errors="replace")
            if status != 200:
                raise KakaoNotificationError(
                    f"[카카오 토큰 갱신 실패] HTTP {status}: {body}"
                )
            token_data = json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise KakaoNotificationError(
            f"[카카오 토큰 갱신 HTTP 오류] HTTP {e.code} ({e.reason}): {err_body}"
        ) from e
    except urllib.error.URLError as e:
        raise KakaoNotificationError(
            f"[카카오 토큰 서버 연결 실패] 네트워크 오류 ({e.reason}). 인터넷 연결 또는 권한을 확인해 주세요."
        ) from e
    except KakaoNotificationError:
        raise
    except Exception as e:
        raise KakaoNotificationError(
            f"[카카오 토큰 갱신 중 예외 발생] {e}"
        ) from e

    access_token = token_data.get("access_token")
    if not access_token:
        raise KakaoNotificationError(
            f"[카카오 토큰 응답 오류] 응답에 access_token이 없습니다: {token_data}"
        )

    if "refresh_token" in token_data and token_data["refresh_token"]:
        update_env_refresh_token(env_path, str(token_data["refresh_token"]))

    return str(access_token)


def build_kakao_template_object(product: Dict[str, object]) -> Dict[str, object]:
    """
    요구사항 2: 메시지에는 상품명, 가격, 쇼핑몰 이름, 리뷰 수를 넣고
    '구매하러 가기' 버튼으로 링크를 설정해 줍니다.
    """
    title = str(product["title"])
    price_str = f"{int(product['price']):,}원"
    mall = str(product["mall"])
    review_str = f"{int(product['review_count']):,}건"
    link = str(product["link"])

    text_body = (
        f"🎉 [특가발견] 목표가격 이하 상품 알림!\n\n"
        f"• 상품명: {title}\n"
        f"• 가격: {price_str}\n"
        f"• 쇼핑몰: {mall}\n"
        f"• 리뷰수: {review_str}"
    )

    return {
        "object_type": "text",
        "text": text_body,
        "link": {
            "web_url": link,
            "mobile_web_url": link,
        },
        "button_title": "구매하러 가기",
    }


def send_kakao_memo(
    product: Dict[str, object],
    env_path: str = DEFAULT_ENV_PATH,
) -> Dict[str, object]:
    """
    카카오톡 '나에게 보내기' API를 호출하여 메시지를 전송합니다.
    실패 시 절대 보낸 척하지 않고 KakaoNotificationError를 발생시킵니다.
    """
    access_token = get_kakao_access_token(env_path=env_path)
    template_obj = build_kakao_template_object(product)

    payload = urllib.parse.urlencode(
        {"template_object": json.dumps(template_obj, ensure_ascii=False)}
    ).encode("utf-8")

    req = urllib.request.Request(
        KAKAO_MEMO_SEND_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            status = getattr(resp, "status", 200)
            body = resp.read().decode("utf-8", errors="replace")
            if status != 200:
                raise KakaoNotificationError(
                    f"[카카오톡 전송 실패] HTTP {status}: {body}"
                )
            res_json = json.loads(body)
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise KakaoNotificationError(
            f"[카카오톡 전송 HTTP 오류] HTTP {e.code} ({e.reason}): {err_body}"
        ) from e
    except urllib.error.URLError as e:
        raise KakaoNotificationError(
            f"[카카오톡 API 연결 실패] 네트워크 오류 ({e.reason})."
        ) from e
    except KakaoNotificationError:
        raise
    except Exception as e:
        raise KakaoNotificationError(
            f"[카카오톡 전송 중 예외 발생] {e}"
        ) from e

    if res_json.get("result_code") != 0:
        raise KakaoNotificationError(
            f"[카카오톡 전송 응답 실패] result_code가 0이 아닙니다: {res_json}"
        )

    return res_json


def clean_html_text(raw: str) -> str:
    """HTML 태그 및 엔티티를 제거하고 공백을 정리합니다."""
    if not raw:
        return ""
    no_tags = re.sub(r"<[^>]+>", " ", raw)
    unescaped = html_lib.unescape(no_tags)
    return re.sub(r"\s+", " ", unescaped).strip()


def fetch_html(url: str, timeout: int = 12) -> str:
    """다나와 공개 웹 엔드포인트에서 HTML을 가져옵니다."""
    req = urllib.request.Request(url, headers=DEFAULT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            if status != 200:
                raise BotValidationError(
                    f"[오류] 다나와 서버 응답 코드가 비정상입니다 (HTTP {status}). URL: {url}"
                )
            raw_bytes = resp.read()
    except urllib.error.HTTPError as e:
        raise BotValidationError(
            f"[오류] 다나와 HTTP 요청 실패 (HTTP {e.code}: {e.reason}). URL: {url}"
        ) from e
    except urllib.error.URLError as e:
        raise BotValidationError(
            f"[오류] 네트워크 연결 또는 다나와 서버 접속에 실패했습니다 ({e.reason}). "
            f"인터넷 연결 또는 샌드박스 네트워크 제한을 확인해 주세요."
        ) from e
    except Exception as e:
        raise BotValidationError(
            f"[오류] 데이터를 가져오는 중 알 수 없는 오류가 발생했습니다: {e}"
        ) from e

    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            text = raw_bytes.decode(enc)
            if text.strip():
                return text
        except UnicodeDecodeError:
            continue

    raise BotValidationError("[오류] 응답 HTML의 문자 인코딩을 해석할 수 없습니다.")


def fetch_lowest_mall_from_ajax(pcode: str) -> Optional[str]:
    """
    danawa-price-search 스킬의 offers 방식:
    getAllPriceCompareMallList.ajax.php 엔드포인트에서 최저가 쇼핑몰 이름을 보조 조회합니다.
    """
    if not pcode or not pcode.isdigit():
        return None
    url = f"{DANAWA_MALL_AJAX_URL}?pcode={urllib.parse.quote(pcode)}"
    req = urllib.request.Request(
        url,
        headers={**DEFAULT_HEADERS, "Referer": f"https://prod.danawa.com/info/?pcode={pcode}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            html_frag = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    mall_match = re.search(
        r'class=["\'][^"\']*diff_item[^"\']*["\'][\s\S]*?<img[^>]+alt=["\']([^"\']+)["\']',
        html_frag,
        re.IGNORECASE,
    )
    if mall_match:
        return clean_html_text(mall_match.group(1))

    alt_match = re.search(
        r'<img[^>]+alt=["\']([^"\']+)["\'][^>]+cmpny_info',
        html_frag,
        re.IGNORECASE,
    )
    if alt_match:
        return clean_html_text(alt_match.group(1))

    return None


def is_ad_or_excluded_item(block_html: str, title: str, price_text: str, exclude_25_sheets: bool = True) -> Tuple[bool, str]:
    """
    1. 광고 상품은 제거하고 실제 판매되는 상품만 필터링합니다.
    2. 검색 상품 중 '25매' 구성 상품은 제외합니다.
    반환값: (제외여부, 사유)
    """
    # 1) 광고 상품 식별 (AD 배지, 애드스마트, 스폰서, 파워링크, 파워쇼핑, loadingBridgeAdSmart 등)
    ad_patterns = [
        r"ad_item",
        r"prod_ad_item",
        r"power_link",
        r"ad_smart",
        r"loadingBridgeAdSmart",
        r"ico_ad",
        r"ad_mark",
        r"애드스마트",
        r"파워쇼핑\s*광고",
        r"광고\s*상품",
        r">광고<",
        r"스폰서",
    ]
    for pat in ad_patterns:
        if re.search(pat, block_html, re.IGNORECASE):
            return True, "광고 상품"

    # 2) 실제 판매되지 않는 상품 식별 (일시품절, 단종, 가격비교 중지, UI 스켈레톤 로딩 블록 등)
    non_sale_keywords = [
        "일시품절",
        "품절",
        "단종",
        "판매중지",
        "가격비교 중지",
        "가격정보 없음",
        "준비중",
        'data-slot="skeleton"',
        "animate-pulse",
    ]
    for kw in non_sale_keywords:
        if kw in block_html or kw in price_text or kw in title:
            return True, f"실제 판매 불가({kw})"

    # 3) 25매 구성 상품 제외 ("단, 검색 상품중 25매 구성 상품은 제외한다.")
    if exclude_25_sheets and (re.search(r"25\s*매", title) or re.search(r"25\s*매", block_html)):
        return True, "25매 구성 상품 제외"

    return False, ""


def parse_danawa_item_block(
    block_html: str,
    exclude_25_sheets: bool = True,
) -> Optional[Dict[str, object]]:
    """
    단일 상품 HTML 블록(구형 li.prod_item 및 2026 신형 li.border-b 모두 호환)에서
    상품명, 가격, 쇼핑몰, 리뷰수, 링크를 추출합니다.
    """
    # 1. pcode 추출
    pcode_match = (
        re.search(r'data-product-seq=["\'](\d+)["\']', block_html)
        or re.search(r'id=["\']productItem(\d+)["\']', block_html)
        or re.search(r'pcode=(\d+)', block_html)
        or re.search(r'data-product-code=["\'](\d+)["\']', block_html)
    )
    pcode = pcode_match.group(1) if pcode_match else ""

    # 2. 상품명 및 링크 추출 (구형 prod_name + 신형 text-px16 leading-22 a)
    title = ""
    link = ""

    # 신형 UI: <p class="mb-2 text-px16 leading-22"><a href="...">...</a></p>
    modern_title_match = re.search(
        r'<p[^>]+class=["\'][^"\']*text-px16[^"\']*["\'][^>]*>\s*<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>',
        block_html,
        re.IGNORECASE,
    )
    if modern_title_match:
        link = html_lib.unescape(modern_title_match.group(1))
        title = clean_html_text(modern_title_match.group(2))
        # 가격비교 카탈로그 상품인데 제목에 '20팩'이 생략된 경우 옵션 태그에서 '20팩' 확인 후 보강
        if "20팩" not in title and "20개" not in title and ">20팩<" in block_html:
            title = f"{title} (20팩)"
    else:
        # 구형 UI: class="prod_name"
        legacy_title_match = (
            re.search(
                r'class=["\'][^"\']*prod_name[^"\']*["\'][\s\S]*?<a[^>]*>([\s\S]*?)</a>',
                block_html,
                re.IGNORECASE,
            )
            or re.search(
                r'<a[^>]+name=["\']productName["\'][^>]*>([\s\S]*?)</a>',
                block_html,
                re.IGNORECASE,
            )
        )
        if legacy_title_match:
            title = clean_html_text(legacy_title_match.group(1))

        link_match = re.search(
            r'<a[^>]+href=["\'](https?://prod\.danawa\.com/(?:info/\?pcode=\d+|bridge/go_link_goods\.php\?)[^"\']*)["\']',
            block_html,
            re.IGNORECASE,
        )
        if link_match:
            link = html_lib.unescape(link_match.group(1))
        elif pcode:
            link = f"https://prod.danawa.com/info/?pcode={pcode}"

    # 3. 가격 추출 (구형 price_sect strong + 신형 text-px16 ... 원)
    raw_price_text = ""
    legacy_price_match = (
        re.search(
            r'class=["\'][^"\']*price_sect[^"\']*["\'][\s\S]*?<strong[^>]*>([\s\S]*?)</strong>',
            block_html,
            re.IGNORECASE,
        )
        or re.search(
            r'class=["\'][^"\']*prc_c[^"\']*["\'][^>]*>([\s\S]*?)</(?:em|strong|span)>',
            block_html,
            re.IGNORECASE,
        )
    )
    if legacy_price_match:
        raw_price_text = clean_html_text(legacy_price_match.group(1))
    else:
        # 신형 UI 가격 패턴: <span class="text-px16...">17,540<!-- -->원</span> 또는 <span>23,120원</span>
        # (단위가격 '116원/10매'나 '배송비 3,000원'과 구분하기 위해 text-px16 클래스 내부의 금액 추출)
        modern_price_match = re.search(
            r'class=["\'][^"\']*text-px16[^"\']*["\'][^>]*>\s*([\d,]+)\s*(?:<!--\s*-->)?\s*원?\s*</span>',
            block_html,
            re.IGNORECASE,
        )
        if modern_price_match:
            raw_price_text = modern_price_match.group(1)

    # 광고, 미판매, 또는 25매 구성 상품(옵션) 필터링
    excluded, _reason = is_ad_or_excluded_item(
        block_html, title, raw_price_text, exclude_25_sheets=exclude_25_sheets
    )
    if excluded:
        return None

    digits = re.sub(r"[^\d]", "", raw_price_text)
    price = int(digits) if digits.isdigit() else -1

    # 4. 쇼핑몰 추출 (구형 mall_name / mall_icon + 신형 cmpny_info 로고 alt / 몰 카운트)
    mall = ""
    mall_match = (
        re.search(
            r'<img[^>]+alt=["\']([^"\']+)["\'][^>]+cmpny_info',
            block_html,
            re.IGNORECASE,
        )
        or re.search(
            r'class=["\'][^"\']*mall_icon[^"\']*["\'][\s\S]*?<img[^>]+alt=["\']([^"\']+)["\']',
            block_html,
            re.IGNORECASE,
        )
        or re.search(
            r'class=["\'][^"\']*mall_name[^"\']*["\'][^>]*>([\s\S]*?)</',
            block_html,
            re.IGNORECASE,
        )
    )
    if mall_match:
        mall = clean_html_text(mall_match.group(1))

    if not mall and pcode:
        mall_count_m = re.search(r'>(\d+)</span>\s*몰<', block_html)
        if mall_count_m:
            mall = f"다나와 가격비교 ({mall_count_m.group(1)}개 쇼핑몰)"
        else:
            mall = "다나와 가격비교 연동몰"

    # 5. 리뷰수 추출 (구형 text__number + 신형 '리뷰수' 뒤 괄호 숫자 + 개별몰 등록 상품은 0건 처리)
    review_count: Optional[int] = None
    review_patterns = [
        r'class=["\'][^"\']*text__number[^"\']*["\'][^>]*>\s*([\d,]+)\s*<',
        r'리뷰수</span>\s*\(\s*<!--\s*-->\s*([\d,]+)\s*<!--\s*-->\s*\)',
        r'리뷰수[\s\S]{0,80}?\(\s*(?:<!--\s*-->)?\s*([\d,]+)\s*(?:<!--\s*-->)?\s*\)',
        r'상품의견[\s\S]{0,80}?<strong[^>]*>\s*([\d,]+)\s*</strong>',
        r'리뷰[\s\S]{0,80}?<(?:strong|em|span)[^>]*>\s*([\d,]+)\s*</(?:strong|em|span)>',
        r'class=["\'][^"\']*cnt_opinion[^"\']*["\'][\s\S]{0,80}?>\s*\(?([\d,]+)\)?\s*<',
    ]
    for rpat in review_patterns:
        rm = re.search(rpat, block_html, re.IGNORECASE)
        if rm:
            r_digits = re.sub(r"[^\d]", "", rm.group(1))
            if r_digits.isdigit():
                review_count = int(r_digits)
                break

    # 다나와 신형 UI에서 리뷰가 아직 0건인 상품은 '리뷰수' 배지 자체를 렌더링하지 않고 '등록' 및 '관심' 버튼만 표시함
    if review_count is None:
        if re.search(r"리뷰\s*0|상품의견\s*0|의견\s*없음", block_html):
            review_count = 0
        elif "등록</span>" in block_html and "리뷰수" not in block_html:
            review_count = 0

    return {
        "pcode": pcode,
        "title": title,
        "price": price,
        "mall": mall,
        "review_count": review_count,
        "link": link,
    }


def validate_product_item(item: Dict[str, object], index: int) -> None:
    """
    잘못된 값을 가져올 경우 지어내지 말고, 무엇이 잘못되었는지 그대로 알려주고 멈춥니다.
    """
    title = item.get("title")
    price = item.get("price")
    mall = item.get("mall")
    review_count = item.get("review_count")
    link = item.get("link")

    if not isinstance(title, str) or len(title.strip()) < 2:
        raise BotValidationError(
            f"[데이터 검증 실패] {index}번째 후보 상품의 '상품명(title)' 값이 비어있거나 잘못되었습니다: {repr(title)}"
        )
    if not isinstance(price, int) or price <= 0:
        raise BotValidationError(
            f"[데이터 검증 실패] '{title}' 상품의 '가격(price)' 값이 유효한 양수가 아닙니다: {repr(price)}"
        )
    if not isinstance(mall, str) or not mall.strip():
        raise BotValidationError(
            f"[데이터 검증 실패] '{title}' 상품의 '쇼핑몰(mall)' 정보를 확인할 수 없습니다: {repr(mall)}"
        )
    if review_count is None or not isinstance(review_count, int) or review_count < 0:
        raise BotValidationError(
            f"[데이터 검증 실패] '{title}' 상품의 '리뷰수(review_count)' 값을 가져오지 못했거나 잘못된 값입니다: {repr(review_count)}"
        )
    if not isinstance(link, str) or not link.startswith("http"):
        raise BotValidationError(
            f"[데이터 검증 실패] '{title}' 상품의 '링크(link)' 주소가 올바르지 않습니다: {repr(link)}"
        )


def extract_item_blocks(html_source: str) -> List[str]:
    """
    다나와 구형 UI(li.prod_item)와 2026년 개편 신형 UI(<ul data-sentry-block="true"> 내부 <li class="border-b...">)를
    모두 지원하여 개별 상품 HTML 블록 리스트를 반환합니다.
    """
    # 1) 구형 UI (li.prod_item) 확인
    legacy_blocks = re.findall(
        r'<li[^>]+class=["\'][^"\']*prod_item[^"\']*["\'][^>]*>[\s\S]*?</li>',
        html_source,
        re.IGNORECASE,
    )
    if legacy_blocks:
        return legacy_blocks

    # 2) 신형 UI (<ul data-sentry-block="true"> 내부의 <li class="border-b...">) 확인
    ul_pos = html_source.find('<ul data-sentry-block="true">')
    search_region = html_source[ul_pos:] if ul_pos != -1 else html_source
    modern_blocks = re.findall(
        r'<li\s+class="border-b[^"]*"[^>]*>[\s\S]*?(?=<li\s+class="border-b|</ul>)',
        search_region,
        re.IGNORECASE,
    )
    return modern_blocks


def search_danawa_lowest(
    keyword: str = "베베앙 20개",
    top_n: int = 3,
    html_source: Optional[str] = None,
    exclude_25_sheets: bool = True,
) -> List[Dict[str, object]]:
    """
    1. '다나와' 검색 스킬 방식으로 키워드를 검색하고
    2. 광고, 미판매 상품 및 '25매' 구성 상품을 제외한 뒤
    3. 최저가 순으로 정렬하여 상위 top_n개 상품을 반환합니다.
    """
    if not keyword or not keyword.strip():
        raise BotValidationError("[입력 오류] 검색 키워드가 비어 있습니다.")

    if html_source is None:
        params = urllib.parse.urlencode({"query": keyword, "sort": "priceASC"})
        url = f"{DANAWA_SEARCH_URL}?{params}"
        html_source = fetch_html(url)

    if not html_source or len(html_source.strip()) < 50:
        raise BotValidationError("[오류] 다나와 검색 응답 HTML이 비어 있거나 너무 짧습니다.")

    item_blocks = extract_item_blocks(html_source)
    if not item_blocks:
        raise BotValidationError(
            f"[파싱 오류] 다나와 검색 결과에서 상품 목록을 찾을 수 없습니다. "
            f"(검색어: '{keyword}')"
        )

    valid_items: List[Dict[str, object]] = []
    for idx, block in enumerate(item_blocks, start=1):
        parsed = parse_danawa_item_block(block, exclude_25_sheets=exclude_25_sheets)
        if parsed is None:
            continue
        validate_product_item(parsed, idx)
        valid_items.append(parsed)

    if len(valid_items) < top_n:
        raise BotValidationError(
            f"[결과 부족 오류] 광고·미판매·25매 구성 상품을 제외한 실제 판매 상품이 {len(valid_items)}개뿐입니다. "
            f"(최소 {top_n}개 필요)"
        )

    valid_items.sort(key=lambda x: int(x["price"]))
    return valid_items[:top_n]


def evaluate_target_price(best_price: int, target_price: int = 20000) -> str:
    """
    1위 가격이 목표가(20,000원) 이하인지 확인 후 지정된 문구를 반환합니다.
    """
    if not isinstance(best_price, int) or best_price <= 0:
        raise BotValidationError(
            f"[검증 오류] 1위 가격 값이 유효하지 않아 목표가 비교를 수행할 수 없습니다: {repr(best_price)}"
        )
    if best_price <= target_price:
        return "[특가발견] 목표가격이하입니다."
    return "[유지] 아직 목표 가격보다 비싸요!"


def print_results(
    keyword: str,
    products: List[Dict[str, object]],
    target_price: int = 20000,
    send_kakao: bool = False,
    env_path: str = DEFAULT_ENV_PATH,
) -> None:
    """
    최저가 순서로 상품 3개를 화면에 보기 좋게 출력하고,
    1위 가격이 목표가 이하일 때만 카카오톡 '나에게 보내기' 알림을 전송합니다.
    목표가보다 비싸면 화면에만 출력하고 메시지는 보내지 않습니다.
    """
    print("=" * 78)
    print(f"🛒 [다나와 최저가 알림 봇] 검색 키워드: '{keyword}' (최저가순 TOP {len(products)})")
    print("   ※ 광고 상품 제거 / 25매 구성 상품 제외 / 실제 판매 상품만 필터링됨")
    print("=" * 78)

    for rank, item in enumerate(products, start=1):
        price_str = f"{int(item['price']):,}원"
        review_str = f"{int(item['review_count']):,}건"
        print(f"[{rank}위] {item['title']}")
        print(f"  • 가격   : {price_str}")
        print(f"  • 쇼핑몰 : {item['mall']}")
        print(f"  • 리뷰수 : {review_str}")
        print(f"  • 링크   : {item['link']}")
        print("-" * 78)

    first_product = products[0]
    first_price = int(first_product["price"])
    status_msg = evaluate_target_price(first_price, target_price=target_price)
    print(f"🎯 1위 상품 가격: {first_price:,}원 (목표가: {target_price:,}원)")
    print(f"📢 판정 결과   : {status_msg}")

    if send_kakao:
        if first_price <= target_price:
            send_kakao_memo(first_product, env_path=env_path)
            print("💬 [카카오톡 알림] 1위 가격이 목표가 이하이므로 '나에게 보내기' 알림을 성공적으로 전송했습니다!")
            print(f"   • 전송 상품 : {first_product['title']} ({first_price:,}원)")
            print(f"   • 버튼 설정 : [구매하러 가기] -> {first_product['link']}")
        else:
            print("🔕 [카카오톡 알림] 1위 가격이 목표가보다 비싸므로 화면에만 출력하고 카카오톡 메시지는 보내지 않았습니다.")

    print("=" * 78)


SAMPLE_DANAWA_HTML = """
<ul class="product_list">
  <li class="prod_item prod_ad_item" id="productItem99999999">
    <span class="ico_ad">AD 애드스마트 광고상품</span>
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=99999999">[광고] 베베앙 스폰서 물티슈 20팩</a></p>
    <div class="price_sect"><strong>9,900</strong>원</div>
    <span class="mall_name">스폰서몰</span>
    <span class="text__number">10</span>
  </li>
  <li class="prod_item" id="productItem88888888">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=88888888">순수코리아 베베앙 단종 물티슈 20팩</a></p>
    <div class="price_sect"><strong>일시품절</strong></div>
    <span class="mall_name">품절몰</span>
    <span class="text__number">5</span>
  </li>
  <li class="prod_item" id="productItem19841201">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=19841201">순수코리아 베베앙 더블 물티슈 캡형 25매 (20팩)</a></p>
    <div class="price_sect"><strong>16,390</strong>원</div>
    <span class="mall_name">다나와 연동 오픈마켓</span>
    <span class="text__number">142</span>
  </li>
  <li class="prod_item" id="productItem17650001">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=17650001">순수코리아 베베앙 프리미엄 골드 캡형 70매 (20팩)</a></p>
    <div class="price_sect"><strong>21,003</strong>원</div>
    <span class="mall_name">다나와 연동몰</span>
    <span class="text__number">215</span>
  </li>
  <li class="prod_item" id="productItem17650002">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=17650002">베베앙 오리지널 플러스 아기 물티슈 캡형 100매 (20팩)</a></p>
    <div class="price_sect"><strong>27,900</strong>원</div>
    <span class="mall_name">쿠팡</span>
    <span class="text__number">890</span>
  </li>
  <li class="prod_item" id="productItem17652310">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=17652310">순수코리아 베베앙 오리지널 아기 물티슈 캡형 100매 (20팩)</a></p>
    <div class="price_sect"><strong>30,100</strong>원</div>
    <span class="mall_name">SK스토아 / G마켓 / 옥션 / 11번가</span>
    <span class="text__number">510</span>
  </li>
</ul>
"""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="다나와(danawa-price-search 스킬 방식) 기반 '베베앙 20개' 최저가 알림 봇"
    )
    parser.add_argument(
        "--until",
        default=None,
        help="봇 유지 만료 시각 (YYYY-MM-DD HH:MM:SS, 지정 시 만료 시각 이후 자동 종료)",
    )
    parser.add_argument(
        "--query",
        default="베베앙 20개",
        help="검색할 키워드 (기본값: '베베앙 20개')",
    )
    parser.add_argument(
        "--target-price",
        type=int,
        default=20000,
        help="목표 가격 (기본값: 20000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="출력할 최저가 상품 개수 (기본값: 3)",
    )
    parser.add_argument(
        "--html-file",
        default=None,
        help="로컬에 저장된 다나와 검색 결과 HTML 파일 경로 (지정 시 네트워크 대신 파일 파싱)",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="다나와 실제 데이터 미러링 샘플로 동작을 검증합니다.",
    )
    parser.add_argument(
        "--no-kakao",
        action="store_true",
        help="카카오톡 메시지 발송을 비활성화하고 콘솔 출력만 수행합니다.",
    )
    parser.add_argument(
        "--env-file",
        default=DEFAULT_ENV_PATH,
        help=".env 파일 경로 (기본값: 프로젝트 폴더 내 .env)",
    )
    args = parser.parse_args()

    if args.until:
        try:
            expire_dt = datetime.strptime(args.until, "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expire_dt:
                print(
                    f"⏹️ [유지 기한 만료] 설정된 유지 시각({args.until})이 지나 프로그램을 자동으로 종료합니다."
                )
                return 0
        except ValueError:
            pass

    try:
        html_source: Optional[str] = None
        if args.html_file:
            try:
                with open(args.html_file, "r", encoding="utf-8") as f:
                    html_source = f.read()
            except Exception as e:
                raise BotValidationError(
                    f"[파일 오류] 지정한 HTML 파일을 읽을 수 없습니다 ({args.html_file}): {e}"
                ) from e
        elif args.demo:
            html_source = SAMPLE_DANAWA_HTML

        products = search_danawa_lowest(
            keyword=args.query,
            top_n=args.limit,
            html_source=html_source,
        )
        print_results(
            keyword=args.query,
            products=products,
            target_price=args.target_price,
            send_kakao=not args.no_kakao,
            env_path=args.env_file,
        )
        return 0

    except BotValidationError as err:
        print("\n" + "!" * 78, file=sys.stderr)
        print("⛔ [봇 실행 중단] 잘못된 값 또는 오류가 감지되어 결과를 지어내지 않고 멈춥니다.", file=sys.stderr)
        print(f"   원인: {err}", file=sys.stderr)
        print("!" * 78, file=sys.stderr)
        return 1
    except KakaoNotificationError as kerr:
        print("\n" + "!" * 78, file=sys.stderr)
        print("⛔ [카카오톡 알림 전송 실패] 메시지를 보내지 못했습니다. 보낸 척하지 않고 원인을 그대로 알려드립니다.", file=sys.stderr)
        print(f"   원인: {kerr}", file=sys.stderr)
        print("!" * 78, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
