"""현재 네이버 로그인 화면(#loginStay, #loginBtn_row/#loginBtn_column) 대응."""
import asyncio

import source_naverpaper as np


class FakeElement:
    def __init__(self, page, selector, tag="input", visible=True, clickable=True):
        self.page = page
        self.selector = selector
        self.tag = tag
        self.visible = visible
        self.clickable = clickable
        self.checked = False


class FakeLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector

    def _elements(self):
        parts = [p.strip() for p in self.selector.split(",")]
        return [el for p in parts for el in self.page.elements if el.selector == p]

    @property
    def first(self):
        return self

    def nth(self, idx):
        return self

    async def count(self):
        return len(self._elements())

    async def is_visible(self):
        els = self._elements()
        return bool(els) and els[0].visible

    async def is_checked(self):
        return self._elements()[0].checked

    async def evaluate(self, script):
        return self._elements()[0].tag

    async def click(self, timeout=None, force=False):
        els = self._elements()
        if not els:
            raise TimeoutError(f"no element {self.selector}")
        el = els[0]
        if not el.clickable or (not el.visible and not force):
            raise TimeoutError(f"element not clickable {self.selector}")
        self.page.clicked.append(el.selector)
        target = self.page.label_targets.get(el.selector)
        if target:
            for other in self.page.elements:
                if other.selector == target:
                    other.checked = not other.checked
        elif el.tag == "input":
            el.checked = not el.checked


class FakePage:
    def __init__(self):
        self.elements = []
        self.clicked = []
        self.label_targets = {}

    def add(self, selector, **kwargs):
        self.elements.append(FakeElement(self, selector, **kwargs))

    def locator(self, selector):
        return FakeLocator(self, selector)


def _current_naver_login_page():
    page = FakePage()
    # 실제 페이지: 체크박스 input은 CSS로 숨겨져 있고 label을 눌러야 토글된다.
    page.add("#loginStay", tag="input", visible=False, clickable=False)
    page.add("label[for='loginStay']", tag="label")
    page.label_targets["label[for='loginStay']"] = "#loginStay"
    page.add("#loginBtn_column", tag="button", visible=False)
    page.add("#loginBtn_row", tag="button", visible=True)
    return page


def test_keep_login_is_enabled_on_current_naver_page():
    page = _current_naver_login_page()
    logs = []

    ok = asyncio.run(np.set_keep_login(page, True, logs.append, "user1"))

    assert ok is True
    stay = [el for el in page.elements if el.selector == "#loginStay"][0]
    assert stay.checked is True
    assert not any("not found" in m for m in logs)


def test_keep_login_not_toggled_when_already_set():
    page = _current_naver_login_page()
    [el for el in page.elements if el.selector == "#loginStay"][0].checked = True

    asyncio.run(np.set_keep_login(page, True, lambda m: None, "user1"))

    assert page.clicked == []


def test_submit_clicks_visible_login_button():
    page = _current_naver_login_page()

    clicked = asyncio.run(np.click_login_submit(page))

    assert clicked == "#loginBtn_row"


def test_submit_reports_failure_when_no_button():
    """버튼이 없으면 → None을 돌려 호출부가 Enter로 폴백할 수 있어야 한다."""
    page = FakePage()

    assert asyncio.run(np.click_login_submit(page)) is None
