"""Rendered browser + HTTPS Go + real disposable Postgres. Synthetic upstream only.
Run the Go TestConfigurationBrowserHarness fixture first; never uses experiment keys.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ready = Path(os.environ['CONFIG_BROWSER_READY_FILE'])
base = json.loads(ready.read_text())['url']
out = Path('integration/evidence/user-config-v03')
out.mkdir(parents=True, exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless=True)
    context = browser.new_context(ignore_https_errors=True, viewport={'width': 1440, 'height': 1050})
    page = context.new_page()
    def open_settings():
        page.goto(base)
        page.get_by_role('button', name='用户配置中心', exact=True).click()
    def cooldown():
        assert context.request.get(base+'/_test/cooldown').status == 204
    try:
        open_settings()
        expect(page.get_by_text('Git 登录不能授权这些接口。', exact=False)).to_be_visible()
        assert context.request.get(base+'/_test/login').status == 204
        open_settings()
        expect(page.get_by_text('未配置 AI 模型', exact=True)).to_be_visible()
        page.get_by_label('配置名称', exact=True).fill('Browser DeepSeek')
        page.get_by_label('API Key', exact=True).fill('browser-synthetic-original-key')
        page.get_by_role('button', name='保存配置', exact=True).click()
        expect(page.get_by_label('API Key', exact=True)).to_have_value('')
        expect(page.get_by_text('凭据：已保存，不可查看', exact=True)).to_be_visible()
        assert page.evaluate('localStorage.length') == 0
        open_settings()
        expect(page.get_by_text('凭据：已保存，不可查看', exact=True)).to_be_visible()
        expect(page.get_by_label('API Key', exact=True)).to_have_value('')
        page.get_by_role('button', name='测试连接', exact=True).click()
        expect(page.get_by_text('服务端收到有效回复，测试成功。', exact=True)).to_be_visible()
        page.get_by_role('button', name='设为默认', exact=True).click()
        expect(page.get_by_text('已设为后续绑定默认。', exact=True)).to_be_visible()
        page.screenshot(path=str(out/'llm-configured.png'), full_page=True)
        page.get_by_role('button', name='编辑', exact=True).click()
        page.get_by_label('API Key', exact=True).fill('browser-synthetic-rotated-key')
        page.get_by_role('button', name='更新密钥', exact=True).click()
        expect(page.get_by_text('密钥已更新，请重新测试并设为默认。', exact=True)).to_be_visible()
        cooldown()
        page.get_by_role('button', name='测试连接', exact=True).click()
        expect(page.get_by_text('服务端收到有效回复，测试成功。', exact=True)).to_be_visible()
        page.get_by_role('button', name='编辑', exact=True).click()
        page.get_by_label('API Key', exact=True).fill('invalid-browser-synthetic-key')
        page.get_by_role('button', name='更新密钥', exact=True).click()
        expect(page.get_by_text('密钥已更新，请重新测试并设为默认。', exact=True)).to_be_visible()
        cooldown()
        page.get_by_role('button', name='测试连接', exact=True).click()
        expect(page.get_by_text('服务商拒绝密钥（401/403）。请更新密钥后重新测试。', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='设为默认', exact=True)).to_be_disabled()
        open_settings()
        expect(page.get_by_text('验证失败', exact=False)).to_be_visible()
        page.screenshot(path=str(out/'llm-failed.png'), full_page=True)
        page.get_by_role('button', name='TTS 音色', exact=True).click()
        page.get_by_label('配置名称', exact=True).fill('Browser XiaoYa')
        page.get_by_label('语速', exact=True).fill('1.2')
        page.get_by_role('button', name='保存配置', exact=True).click()
        expect(page.get_by_text('Browser XiaoYa · xiaoya', exact=True)).to_be_visible()
        open_settings()
        page.get_by_role('button', name='TTS 音色', exact=True).click()
        expect(page.get_by_text('Browser XiaoYa · xiaoya', exact=True)).to_be_visible()
        page.get_by_role('button', name='编辑', exact=True).click()
        expect(page.get_by_label('语速', exact=True)).to_have_value('1.2')
        page.get_by_role('button', name='Avatar', exact=True).click()
        page.get_by_label('配置名称', exact=True).fill('Browser Avatar')
        page.get_by_label('Avatar 逻辑引用', exact=True).fill('avatar-browser-reference')
        page.get_by_role('button', name='保存配置', exact=True).click()
        expect(page.get_by_text('Browser Avatar · mock', exact=True)).to_be_visible()
        page.get_by_role('button', name='GPU Worker', exact=True).click()
        page.get_by_label('配置名称', exact=True).fill('Browser Worker')
        page.get_by_role('button', name='保存配置', exact=True).click()
        expect(page.get_by_text('Browser Worker · soulx', exact=True)).to_be_visible()
        expect(page.get_by_text('Worker 健康：未知 / 未上报', exact=True)).to_be_visible()
        page.screenshot(path=str(out/'worker-unreported.png'), full_page=True)
        result = {'status': 'PASS', 'transport': 'loopback HTTPS test certificate', 'database': 'isolated PostgreSQL', 'upstream': 'SYNTHETIC ONLY', 'realDeepSeek': 'NOT VERIFIED', 'browser': 'Chrome', 'checks': ['unauthenticated denial', 'save key', 'refresh safe metadata', 'test success', 'default selection', 'rotate key', 'upstream 401 failure', 'persisted failed state', 'TTS save/read speed', 'Avatar save', 'Worker UNKNOWN', 'no localStorage secrets']}
        (out/'browser-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps(result, ensure_ascii=False))
    finally:
        context.request.get(base+'/_test/stop')
        context.close()
        browser.close()
