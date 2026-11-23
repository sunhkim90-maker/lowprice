#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_lowprice_bot.py
lowprice_bot.py가 핵심 요구사항(기존 4대 검사 + 신규 25매 제외 및 카카오톡 나에게 보내기 연동)을
정확히 만족하는지 가상 데이터(Mock HTML & Mock Kakao API)만으로 엄격하게 검증하는 테스트 스크립트입니다.

[검사 내용]
1. 20,000원 이하일 때 특가 메시지가 출력되고 카카오톡 알림(상품명/가격/쇼핑몰/리뷰수 + '구매하러 가기' 버튼)이 전송되는가? (단, 25매 구성 상품은 제외)
2. 20,000원 초과일 때 유지 메시지가 출력되고 카카오톡 알림은 보내지 않는가?
3. 광고 상품(및 25매 구성 상품)이 섞여 있을 때 걸러낼 수 있는가?
4. 값을 가져오지 못했거나 카카오톡 알림을 못 보냈을 때 보낸 척하지 않고 무엇이 잘못되었는지 오류를 그대로 알려주는가?
"""

import contextlib
import io
import sys
from typing import Callable, List, Tuple

import lowprice_bot

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def block_network_access(*args, **kwargs):
    """실제 외부 사이트에 요청이 나가지 않도록 네트워크 호출을 원천 차단합니다."""
    raise RuntimeError("테스트 중 실제 외부 네트워크 요청이 감지되었습니다! 가상 데이터만 사용해야 합니다.")


lowprice_bot.urllib.request.urlopen = block_network_access


# ---------------------------------------------------------------------------
# 가상 데이터 (Mock HTML) 정의
# ---------------------------------------------------------------------------

# 1. 25매 상품(15,000원)이 섞여 있으나 제외되고, 70매 실제 1위 가격이 20,000원 이하(18,500원)인 가상 데이터
MOCK_HTML_UNDER_20000 = """
<ul class="product_list">
  <li class="prod_item" id="productItem1000">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=1000">베베앙 더블 물티슈 캡형 25매 20개</a></p>
    <div class="price_sect"><strong>15,000</strong>원</div>
    <span class="mall_name">11번가</span>
    <span class="text__number">99</span>
  </li>
  <li class="prod_item" id="productItem1001">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=1001">베베앙 라이트 물티슈 캡형 70매 20개</a></p>
    <div class="price_sect"><strong>18,500</strong>원</div>
    <span class="mall_name">11번가</span>
    <span class="text__number">120</span>
  </li>
  <li class="prod_item" id="productItem1002">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=1002">베베앙 프리미엄 골드 물티슈 70매 20개</a></p>
    <div class="price_sect"><strong>21,500</strong>원</div>
    <span class="mall_name">G마켓</span>
    <span class="text__number">340</span>
  </li>
  <li class="prod_item" id="productItem1003">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=1003">베베앙 오리지널 아기 물티슈 100매 20개</a></p>
    <div class="price_sect"><strong>25,900</strong>원</div>
    <span class="mall_name">옥션</span>
    <span class="text__number">510</span>
  </li>
</ul>
"""

# 2. 1위 가격이 20,000원 초과(22,900원)인 정상 가상 데이터
MOCK_HTML_OVER_20000 = """
<ul class="product_list">
  <li class="prod_item" id="productItem2001">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=2001">베베앙 프리미엄 골드 물티슈 70매 20개</a></p>
    <div class="price_sect"><strong>22,900</strong>원</div>
    <span class="mall_name">G마켓</span>
    <span class="text__number">215</span>
  </li>
  <li class="prod_item" id="productItem2002">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=2002">베베앙 오리지널 플러스 물티슈 100매 20개</a></p>
    <div class="price_sect"><strong>26,400</strong>원</div>
    <span class="mall_name">쿠팡</span>
    <span class="text__number">890</span>
  </li>
  <li class="prod_item" id="productItem2003">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=2003">베베앙 시그니처 물티슈 100매 20개</a></p>
    <div class="price_sect"><strong>29,800</strong>원</div>
    <span class="mall_name">11번가</span>
    <span class="text__number">430</span>
  </li>
</ul>
"""

# 3. 초저가 광고 상품(AD 애드스마트, 파워링크 등)과 25매 상품이 섞여 있는 가상 데이터
MOCK_HTML_WITH_ADS = """
<ul class="product_list">
  <li class="prod_item prod_ad_item" id="productItem9001">
    <span class="ico_ad">AD 애드스마트 광고상품</span>
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=9001">[광고] 초특가 스폰서 베베앙 물티슈 100매 20개</a></p>
    <div class="price_sect"><strong>5,000</strong>원</div>
    <span class="mall_name">스폰서광고몰</span>
    <span class="text__number">999</span>
  </li>
  <li class="prod_item power_link" id="productItem9002">
    <span class="ad_mark">광고</span>
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=9002">파워링크 베베앙 물티슈 100매 20개</a></p>
    <div class="price_sect"><strong>7,000</strong>원</div>
    <span class="mall_name">파워링크몰</span>
    <span class="text__number">88</span>
  </li>
  <li class="prod_item" id="productItem9003">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=9003">베베앙 휴대용 물티슈 25매 20개</a></p>
    <div class="price_sect"><strong>12,000</strong>원</div>
    <span class="mall_name">휴대몰</span>
    <span class="text__number">77</span>
  </li>
  <li class="prod_item" id="productItem3001">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=3001">베베앙 실제판매 1위 물티슈 70매 20개</a></p>
    <div class="price_sect"><strong>17,900</strong>원</div>
    <span class="mall_name">옥션</span>
    <span class="text__number">150</span>
  </li>
  <li class="prod_item" id="productItem3002">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=3002">베베앙 실제판매 2위 물티슈 100매 20개</a></p>
    <div class="price_sect"><strong>21,000</strong>원</div>
    <span class="mall_name">G마켓</span>
    <span class="text__number">260</span>
  </li>
  <li class="prod_item" id="productItem3003">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=3003">베베앙 실제판매 3위 물티슈 100매 20개</a></p>
    <div class="price_sect"><strong>24,500</strong>원</div>
    <span class="mall_name">11번가</span>
    <span class="text__number">310</span>
  </li>
</ul>
"""

# 4. 가격 등 필수 값을 가져오지 못한 불완전/오류 가상 데이터
MOCK_HTML_MISSING_PRICE = """
<ul class="product_list">
  <li class="prod_item" id="productItem4001">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=4001">베베앙 가격누락 오류 물티슈 100매 20개</a></p>
    <div class="price_sect"><strong></strong></div>
    <span class="mall_name">11번가</span>
    <span class="text__number">100</span>
  </li>
  <li class="prod_item" id="productItem4002">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=4002">베베앙 정상 물티슈 100매 20개 B</a></p>
    <div class="price_sect"><strong>19,000</strong>원</div>
    <span class="mall_name">G마켓</span>
    <span class="text__number">200</span>
  </li>
  <li class="prod_item" id="productItem4003">
    <p class="prod_name"><a href="https://prod.danawa.com/info/?pcode=4003">베베앙 정상 물티슈 100매 20개 C</a></p>
    <div class="price_sect"><strong>22,000</strong>원</div>
    <span class="mall_name">옥션</span>
    <span class="text__number">300</span>
  </li>
</ul>
"""


def check_1_under_20000() -> Tuple[bool, str]:
    """검사 1: 20,000원 이하일 때(25매 제외 후) 특가 메시지가 출력되고 카카오톡 템플릿이 정확히 구성·발송되는가?"""
    products = lowprice_bot.search_danawa_lowest(
        keyword="베베앙 20개", top_n=3, html_source=MOCK_HTML_UNDER_20000
    )
    sent_records = []

    def mock_send_kakao(product, env_path=""):
        tmpl = lowprice_bot.build_kakao_template_object(product)
        sent_records.append(tmpl)
        return {"result_code": 0}

    orig_send = lowprice_bot.send_kakao_memo
    lowprice_bot.send_kakao_memo = mock_send_kakao
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            lowprice_bot.print_results(
                "베베앙 20개", products, target_price=20000, send_kakao=True
            )
        output = buf.getvalue()
    finally:
        lowprice_bot.send_kakao_memo = orig_send

    expected_msg = "[특가발견] 목표가격이하입니다."
    if len(products) != 3:
        return False, f"상품 3개가 반환되지 않음 (반환 수: {len(products)})"
    if any("25매" in str(p["title"]) for p in products):
        return False, "25매 구성 상품이 제외되지 않고 결과에 포함됨"
    if products[0]["price"] != 18500:
        return False, f"25매 제외 후 1위 가격이 18,500원이 아님 ({products[0]['price']})"
    if expected_msg not in output:
        return False, f"출력에 '{expected_msg}' 문구가 포함되지 않음"
    if len(sent_records) != 1:
        return False, f"목표가 이하임에도 카카오톡 알림이 전송되지 않음 (전송 횟수: {len(sent_records)})"

    tmpl = sent_records[0]
    text_body = tmpl.get("text", "")
    if tmpl.get("button_title") != "구매하러 가기":
        return False, f"버튼 이름이 '구매하러 가기'가 아님: {tmpl.get('button_title')}"
    if tmpl.get("link", {}).get("web_url") != "https://prod.danawa.com/info/?pcode=1001":
        return False, f"버튼 링크가 올바르지 않음: {tmpl.get('link')}"
    for required_field in ("베베앙 라이트 물티슈 캡형 70매 20개", "18,500원", "11번가", "120건"):
        if required_field not in text_body:
            return False, f"카카오톡 메시지 본문에 필수 정보({required_field})가 누락됨: {text_body}"

    return True, f"25매 제외 후 1위(18,500원) 확인, '{expected_msg}' 출력 및 카톡('구매하러 가기' 버튼 포함) 발송 확인"


def check_2_over_20000() -> Tuple[bool, str]:
    """검사 2: 20,000원 초과일 때 유지 메시지가 출력되고 카카오톡 메시지는 보내지 않는가?"""
    products = lowprice_bot.search_danawa_lowest(
        keyword="베베앙 20개", top_n=3, html_source=MOCK_HTML_OVER_20000
    )
    sent_records = []

    def mock_send_kakao(product, env_path=""):
        sent_records.append(product)
        return {"result_code": 0}

    orig_send = lowprice_bot.send_kakao_memo
    lowprice_bot.send_kakao_memo = mock_send_kakao
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            lowprice_bot.print_results(
                "베베앙 20개", products, target_price=20000, send_kakao=True
            )
        output = buf.getvalue()
    finally:
        lowprice_bot.send_kakao_memo = orig_send

    expected_msg = "[유지] 아직 목표 가격보다 비싸요!"
    if len(products) != 3:
        return False, f"상품 3개가 반환되지 않음 (반환 수: {len(products)})"
    if products[0]["price"] != 22900:
        return False, f"1위 가격이 22,900원이 아님 ({products[0]['price']})"
    if expected_msg not in output:
        return False, f"출력에 '{expected_msg}' 문구가 포함되지 않음"
    if len(sent_records) != 0:
        return False, f"목표가 초과임에도 카카오톡 알림이 잘못 발송됨 ({len(sent_records)}건)"
    return True, f"1위 가격 22,900원 확인, '{expected_msg}' 출력 및 카카오톡 미발송(화면에만 출력) 확인"


def check_3_filter_ads() -> Tuple[bool, str]:
    """검사 3: 광고 상품(및 25매 구성 상품)이 섞여 있을 때 걸러낼 수 있는가?"""
    products = lowprice_bot.search_danawa_lowest(
        keyword="베베앙 20개", top_n=3, html_source=MOCK_HTML_WITH_ADS
    )
    titles = [str(p["title"]) for p in products]
    prices = [int(p["price"]) for p in products]

    if len(products) != 3:
        return False, f"광고 및 25매 제거 후 실제 상품 3개가 반환되지 않음 (반환 수: {len(products)})"
    for t in titles:
        if "광고" in t or "파워링크" in t or "스폰서" in t or "25매" in t:
            return False, f"제외 대상 상품(광고/25매)이 결과에 포함됨: {t}"
    if prices != [17900, 21000, 24500]:
        return False, f"실제 판매 상품의 최저가 정렬 순서가 일치하지 않음: {prices}"
    return True, "광고 상품 2건 및 25매 상품 1건 완벽 제거, 실제 판매 상품 3건(17,900원~24,500원) 정상 추출"


def check_4_missing_value_error_handling() -> Tuple[bool, str]:
    """검사 4: 값을 가져오지 못했거나 카카오톡 알림 전송 실패 시 보낸 척하지 않고 오류 원인을 그대로 알려주는가?"""
    # 4-1) 필수 값(가격)이 누락된 HTML 검증
    try:
        lowprice_bot.search_danawa_lowest(
            keyword="베베앙 20개", top_n=3, html_source=MOCK_HTML_MISSING_PRICE
        )
        return False, "가격이 누락된 잘못된 데이터를 통과시키거나 임의의 값을 지어냄"
    except lowprice_bot.BotValidationError as e:
        err_msg = str(e)
        if "가격(price)" not in err_msg and "데이터 검증 실패" not in err_msg:
            return False, f"오류 메시지에 구체적인 실패 원인이 없음: {err_msg}"
    except Exception as e:
        return False, f"제어되지 않은 비정상 예외(Crash) 발생: {type(e).__name__}: {e}"

    # 4-2) 카카오톡 알림 전송 실패(예: .env 파일 누락 또는 잘못된 토큰) 시 보낸 척하지 않고 KakaoNotificationError 발생 확인
    try:
        lowprice_bot.send_kakao_memo(
            {
                "title": "테스트 물티슈 100매 20개",
                "price": 18000,
                "mall": "11번가",
                "review_count": 50,
                "link": "https://prod.danawa.com/info/?pcode=1001",
            },
            env_path="c:/agapp_project/lowprice/.non_existent_env_for_test",
        )
        return False, "카카오 인증 정보가 없는데도 알림을 보낸 척 통과함"
    except lowprice_bot.KakaoNotificationError as ke:
        k_msg = str(ke)
        if ".env" not in k_msg and "인증" not in k_msg:
            return False, f"카카오톡 실패 원인이 명확하지 않음: {k_msg}"
    except Exception as e:
        return False, f"카카오톡 실패 처리 중 비정상 예외 발생: {type(e).__name__}: {e}"

    return True, f"상품 값 누락({err_msg}) 및 카톡 전송 실패({k_msg}) 시 보낸 척하지 않고 정확한 원인 안내 확인"


def run_all_tests() -> int:
    tests: List[Tuple[str, Callable[[], Tuple[bool, str]]]] = [
        ("1. 20,000원 이하일 때 특가 메시지 출력 및 카톡 알림(구매하러 가기 버튼)이 동작하는가?", check_1_under_20000),
        ("2. 20,000원 초과일 때 유지 메시지만 출력되고 카톡 알림은 보내지 않는가?", check_2_over_20000),
        ("3. 광고 상품(및 25매 구성 상품)이 섞여 있을 때 걸러낼 수 있는가?", check_3_filter_ads),
        ("4. 값을 못 가져왔거나 알림을 못 보냈을 때 오류 원인을 그대로 알려주는가?", check_4_missing_value_error_handling),
    ]

    print("=" * 82)
    print("🧪 [lowprice_bot.py 자동 검증 리포트] (가상 데이터 전용 / 외부 네트워크 요청 0건)")
    print("=" * 82)

    all_passed = True
    for name, func in tests:
        try:
            passed, detail = func()
        except Exception as exc:
            passed = False
            detail = f"예기치 못한 예외 발생: {type(exc).__name__}: {exc}"

        status = "PASS" if passed else "FAIL"
        icon = "✅" if passed else "❌"
        print(f"{icon} [{status}] {name}")
        print(f"   └─ 상세: {detail}")
        if not passed:
            all_passed = False

    print("=" * 82)
    if all_passed:
        print("🎉 최종 결과: 전체 4개 검사 항목 모두 [PASS] 하였습니다!")
        print("=" * 82)
        return 0
    else:
        print("⚠️ 최종 결과: 일부 항목이 [FAIL] 하였습니다. 수정이 필요합니다.")
        print("=" * 82)
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
