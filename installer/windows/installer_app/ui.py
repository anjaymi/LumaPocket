"""Guided, per-user Windows installation surface."""
import os
from pathlib import Path
import queue
import re
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser

from .accounts import account_info, clean_login_temporary
from .paths import ASSETS, data_dir
from .tasks import Task
from .tooling import apple_root_trusted
from . import __version__

BG, INK, MUTED, ACCENT = '#f6f7fb', '#20283a', '#6b7386', '#4e62d9'
ERRORS = {
    'apple_certificate_limit_reached': 'Apple 开发证书名额已满（7460）。登录会话已保留，需要处理现有证书后重试；请勿连续重新登录。',
    'windows_cpp_runtime_required': '请通过“Windows 运行库”链接安装 Microsoft 官方 Visual C++ x64 运行库，再重试。',
    'apple_device_driver_unavailable': '未找到 Apple 设备服务。请先安装 Apple 设备应用，再连接并解锁 iPhone / iPad。',
    'device_trust_required': '请解锁 iPhone / iPad，在设备上信任这台电脑，然后重试。',
    'device_connection_lost': '设备连接已中断。请检查数据线和设备锁屏状态。',
    'device_install_failed': '设备安装未完成。请检查连接、开发者模式和设备剩余空间。',
    'device_rejected_signature': '设备未接受此安装包的签名。请检查签名有效期和设备归属。',
    'ipa_not_signed': '这个 IPA 尚未签名。请先使用“首次签名”流程。',
    'ipa_profile_expired': '这个 IPA 的描述文件已过期，需要重新签名。',
    'ipa_does_not_match_device': '这个 IPA 没有包含当前设备，无法直接安装到它。',
    'ipa_profile_bundle_mismatch': 'IPA 的应用标识与描述文件不一致。',
    'invalid_ipa_file': '无法读取这个 IPA，请选择完整的 .ipa 文件。',
    'invalid_mobileprovision': '安装包的描述文件未通过检查。',
    'github_login_required': '请先登录你自己的 GitHub 账号。',
    'github_login_failed': 'GitHub 登录未完成，可以重新登录。',
    'personal_github_account_required': '请使用个人 GitHub 账号。',
    'personal_signing_repository_needs_security_update': '个人签名仓库需要更新后才能继续授权。',
    'local_profile_in_use_close_other_signing_window': '另一个授权窗口正在使用此账号，请先完成或关闭它。',
    'local_apple_authorization_failed': 'Apple 登录未完成。请核对窗口中的步骤提示后重试。',
    'v3_device_setup_failed_check_network': '独立设备认证连接失败，请检查网络后重试。',
    'single_personal_team_required': '当前流程需要账号中有且只有一个免费的 Personal Team。',
    'different_apple_account_requires_separate_repository': '这个仓库已绑定另一个 Apple 账号，请换一个个人仓库名称。',
    'first_manual_signing_failed_check_actions': '首次云端签名失败。可打开个人仓库查看任务结果。',
    'updated_signer_integrity_check_failed': '签名组件完整性检查失败，请重新获取安装助手。',
}


class Window:
    def __init__(self, root, initial_ipa=None):
        self.root = root
        self.events = queue.Queue()
        self.task = None
        self.busy = False
        self.error = None
        self.devices = []
        self.ipa = None
        self.pending_sign = False
        root.title('LumaPocket · 安装助手 ' + __version__)
        height = min(820, max(620, root.winfo_screenheight() - 100))
        root.geometry('850x' + str(height))
        root.minsize(760, min(620, height))
        if (ASSETS / 'app_icon.ico').is_file():
            root.iconbitmap(str(ASSETS / 'app_icon.ico'))
        root.configure(bg=BG)
        root.protocol('WM_DELETE_WINDOW', self.close)
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('TFrame', background=BG)
        style.configure('TLabel', background=BG, foreground=INK, font=('Microsoft YaHei UI', 10))
        style.configure('TButton', font=('Microsoft YaHei UI', 10), padding=(12, 7))
        style.configure('Primary.TButton', background=ACCENT, foreground='white', padding=(18, 9))
        style.map('Primary.TButton', background=[('active', '#4054c6'), ('disabled', '#c5cbe5')])
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', padding=(20, 9), font=('Microsoft YaHei UI', 10))
        self.build()
        if initial_ipa and Path(initial_ipa).is_file() and Path(initial_ipa).suffix.lower() == '.ipa':
            self.ipa = Path(initial_ipa).resolve()
            self.package.set(str(self.ipa))
            self.tabs.select(self.install_tab)
            self.show_first_launch()
        root.after(100, self.drain)
        root.after(400, self.scan)

    def label(self, parent, text, size=10, color=INK, bold=False, **kwargs):
        return tk.Label(parent, text=text, bg=BG, fg=color, font=('Microsoft YaHei UI', size, 'bold' if bold else 'normal'), **kwargs)

    def build(self):
        outer = ttk.Frame(self.root, padding=(30, 24))
        outer.pack(fill='both', expand=True)
        top = ttk.Frame(outer)
        top.pack(fill='x')
        self.label(top, 'LumaPocket', 23, bold=True).pack(side='left')
        self.label(top, '安装助手 ' + __version__ + ' · 实验版', 10, MUTED).pack(side='left', padx=14, pady=(11, 0))
        ttk.Button(top, text='源码与说明', command=self.export_sources).pack(side='right')
        self.label(outer, '连接 iPhone / iPad，自动获取最新版，用自己的账号签名并安装。', color=MUTED).pack(anchor='w', pady=(5, 22))

        self.label(outer, '01   连接设备', 12, bold=True).pack(anchor='w')
        row = ttk.Frame(outer)
        row.pack(fill='x', pady=(8, 6))
        self.device_box = ttk.Combobox(row, state='readonly', font=('Microsoft YaHei UI', 10))
        self.device_box.pack(side='left', fill='x', expand=True)
        self.device_box.bind('<<ComboboxSelected>>', self.select_device)
        self.scan_button = ttk.Button(row, text='读取设备', command=self.scan)
        self.scan_button.pack(side='left', padx=(10, 0))
        self.udid = tk.StringVar()
        udidrow = ttk.Frame(outer)
        udidrow.pack(fill='x')
        self.label(udidrow, 'UDID', 9, MUTED).pack(side='left', padx=(0, 10))
        ttk.Entry(udidrow, textvariable=self.udid, font=('Microsoft YaHei UI', 10)).pack(side='left', fill='x', expand=True)
        self.label(outer, '用数据线连接、解锁，并在设备上选择“信任”。也可手动填写 UDID 仅做签名。', 9, MUTED).pack(anchor='w', pady=(5, 14))

        self.tabs = ttk.Notebook(outer)
        self.tabs.pack(fill='both', expand=True)
        self.sign_tab = ttk.Frame(self.tabs, padding=(0, 15, 0, 0))
        self.install_tab = ttk.Frame(self.tabs, padding=(0, 15, 0, 0))
        self.tabs.add(self.sign_tab, text='首次签名')
        self.tabs.add(self.install_tab, text='安装与更新')
        self.sign_scroll, sign_content = self.scrollable(self.sign_tab)
        self.install_scroll, install_content = self.scrollable(self.install_tab)
        self.build_sign(sign_content)
        self.build_install(install_content)

        footer = ttk.Frame(outer)
        footer.pack(fill='x', pady=(14, 0))
        self.status = tk.StringVar(value='准备连接设备…')
        status_label = self.label(footer, '', justify='left', wraplength=680)
        status_label.configure(textvariable=self.status)
        status_label.pack(anchor='w', fill='x')
        self.progress = ttk.Progressbar(footer, mode='indeterminate')
        self.progress.pack(fill='x', pady=(9, 8))
        links = ttk.Frame(footer)
        links.pack(fill='x')
        self.cancel_button = ttk.Button(links, text='取消当前任务', state='disabled', command=self.cancel)
        self.cancel_button.pack(side='left')
        ttk.Button(links, text='Windows 运行库', command=lambda: webbrowser.open('https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist')).pack(side='right')
        ttk.Button(links, text='Apple 设备驱动', command=lambda: webbrowser.open('https://support.apple.com/zh-cn/guide/devices-windows/welcome/windows')).pack(side='right')
        ttk.Button(links, text='开发者模式说明', command=lambda: webbrowser.open('https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device')).pack(side='right', padx=8)

    def scrollable(self, parent):
        canvas = tk.Canvas(parent, bg=BG, borderwidth=0, highlightthickness=0)
        bar = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        content = ttk.Frame(canvas)
        item = canvas.create_window(0, 0, window=content, anchor='nw')
        content.bind('<Configure>', lambda _: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda event: canvas.itemconfigure(item, width=event.width))
        def wheel(event):
            target = self.root.winfo_containing(event.x_root, event.y_root)
            while target is not None and target != canvas:
                target = target.master
            if target == canvas and canvas.yview() != (0.0, 1.0):
                canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'
        self.root.bind('<MouseWheel>', wheel, add='+')
        return canvas, content

    def build_sign(self, parent):
        self.label(parent, '02   登录自己的 GitHub 账号', 12, bold=True).pack(anchor='w')
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(9, 7))
        info = account_info()
        self.github = tk.StringVar(value=('已登录：' + info['login']) if info else '尚未登录')
        label = self.label(row, '', color=MUTED)
        label.configure(textvariable=self.github)
        label.pack(side='left')
        self.login_button = ttk.Button(row, text='登录 / 切换 GitHub', command=lambda: self.start('github-login'))
        self.login_button.pack(side='right')
        self.label(parent, '应用由 LumaPocket 公开发布页提供，不需要你准备或上传源码。\n助手会自动创建你的个人签名仓库，签名状态按账号隔离并加密保存。', 9, MUTED, justify='left', wraplength=680).pack(anchor='w')
        form = ttk.Frame(parent)
        form.pack(fill='x', pady=(16, 4))
        self.label(form, '03   Apple 账号邮箱', 12, bold=True).grid(row=0, column=0, sticky='w')
        self.email = ttk.Entry(form, font=('Microsoft YaHei UI', 11))
        self.email.grid(row=1, column=0, sticky='ew', pady=(7, 0), padx=(0, 16))
        self.label(form, '个人仓库名称', 9, MUTED).grid(row=0, column=1, sticky='w')
        self.repo = ttk.Entry(form, width=25, font=('Microsoft YaHei UI', 10))
        self.repo.insert(0, 'LumaPocket-Cloud')
        self.repo.grid(row=1, column=1, sticky='ew', pady=(7, 0))
        form.columnconfigure(0, weight=1)
        self.sign_button = ttk.Button(parent, text='创建个人仓库并开始授权', style='Primary.TButton', command=self.sign)
        self.sign_button.pack(anchor='w', pady=(12, 8))
        self.challenge = ttk.Frame(parent)
        self.challenge.pack(fill='x')
        self.label(parent, '密码和验证码在本机窗口输入。免费签名有有效期，云端重签后仍需安装刷新到设备。', 9, MUTED, justify='left', wraplength=680).pack(anchor='w', pady=(10, 0))

    def build_install(self, parent):
        self.label(parent, '选择为这台设备签过名的 IPA', 12, bold=True).pack(anchor='w')
        self.package = tk.StringVar(value='尚未选择安装包')
        label = self.label(parent, '', color=MUTED, justify='left', wraplength=680)
        label.configure(textvariable=self.package)
        label.pack(anchor='w', pady=(12, 14))
        row = ttk.Frame(parent)
        row.pack(anchor='w')
        self.pick_button = ttk.Button(row, text='选择 IPA…', command=self.pick)
        self.pick_button.pack(side='left')
        self.install_button = ttk.Button(row, text='安装到所选设备', style='Primary.TButton', command=self.install)
        self.install_button.pack(side='left', padx=10)
        ttk.Button(row, text='首次打开提示', command=self.show_first_launch).pack(side='left')
        self.label(parent, '安装前检查设备归属和有效期。未签名、已过期或属于其他设备的 IPA 会被拦下。', 9, MUTED, justify='left', wraplength=680).pack(anchor='w', pady=(12, 24))
        self.first_launch = ttk.Frame(parent)
        self.first_launch.pack(fill='x')
        self.label(parent, '已有个人签名仓库', 12, bold=True).pack(anchor='w')
        self.download_button = ttk.Button(parent, text='下载我的最新签名包', command=lambda: self.start('download'))
        self.download_button.pack(anchor='w', pady=10)
        controls = ttk.Frame(parent)
        controls.pack(anchor='w', pady=(12, 0))
        ttk.Button(controls, text='打开安装包文件夹', command=self.open_downloads).pack(side='left')
        ttk.Button(controls, text='将 IPA 另存为…', command=self.save_ipa).pack(side='left', padx=10)

    def show_first_launch(self):
        for child in self.first_launch.winfo_children():
            child.destroy()
        self.label(self.first_launch, '在 iPhone / iPad 上完成首次打开', 11, bold=True).pack(anchor='w')
        self.label(self.first_launch,
            '① 设置 → 通用 → VPN 与设备管理 → 开发者 App，选择本次签名的 Apple 账号，点“信任”或“验证 App”。验证时保持联网。\n'
            '② 如果提示需要开发者模式：设置 → 隐私与安全性 → 开发者模式，开启后按系统提示重启。\n'
            '③ 回到主屏幕打开 LumaPocket。若系统显示“允许并重新启动”，按该提示完成。',
            9, MUTED, justify='left', wraplength=680).pack(anchor='w', pady=(7, 16))

    def set_busy(self, busy):
        self.busy = busy
        for button in (self.scan_button, self.login_button, self.sign_button, self.pick_button, self.install_button, self.download_button):
            button.configure(state='disabled' if busy else 'normal')
        self.cancel_button.configure(state='normal' if busy else 'disabled')
        if busy:
            self.progress.configure(mode='indeterminate')
            self.progress.start(12)
        else:
            self.progress.stop()

    def start(self, action, *args, **inputs):
        if self.busy:
            return
        self.error = None
        self.set_busy(True)
        self.status.set('正在准备，请稍候…')
        self.task = Task(lambda name, detail: self.events.put((name, detail)))
        self.task.start(action, *args, **inputs)

    def scan(self):
        self.start('devices')

    def select_device(self, event=None):
        index = self.device_box.current()
        if 0 <= index < len(self.devices):
            self.udid.set(self.devices[index]['udid'])

    def valid_udid(self):
        value = self.udid.get().strip()
        if not re.fullmatch(r'(?:[0-9a-fA-F]{8}-[0-9a-fA-F]{16}|[0-9a-fA-F]{40})', value):
            messagebox.showwarning('连接设备', '请先读取设备或填写有效 UDID。', parent=self.root)
            return None
        return value

    def sign(self):
        udid, email, name = self.valid_udid(), self.email.get().strip(), self.repo.get().strip()
        if not udid:
            return
        if not account_info():
            messagebox.showinfo('先登录 GitHub', '请先登录你自己的 GitHub 账号。', parent=self.root)
            return
        if not re.fullmatch(r'[^\s:@]+@[^\s:@]+\.[^\s:@]+', email) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,80}', name):
            messagebox.showwarning('检查填写内容', '请检查 Apple 账号邮箱和个人仓库名称。', parent=self.root)
            return
        if not apple_root_trusted():
            approved = messagebox.askyesno('Apple 官方证书',
                '签名工具需要信任 Apple 官方根证书。允许将已核对指纹的 Apple Root CA 加入当前 Windows 用户的受信任根证书库吗？\n\n'
                '这会影响此用户其他应用的 TLS 信任，可以之后移除。', parent=self.root)
            if not approved:
                return
            self.pending_sign = True
            self.start('trust-apple-root')
            return
        self.start('onboard', name, udid=udid, account=email)

    def pick(self):
        value = filedialog.askopenfilename(parent=self.root, title='选择已签名 IPA', filetypes=[('iOS 安装包', '*.ipa')])
        if value:
            self.ipa = Path(value)
            self.package.set(str(self.ipa))

    def install(self):
        udid = self.valid_udid()
        if not udid:
            return
        if not self.ipa:
            self.pick()
        if self.ipa:
            self.start('install', str(self.ipa), udid)

    def clear_challenge(self):
        for child in self.challenge.winfo_children():
            child.destroy()

    def input_challenge(self, label, secret=False, code=False):
        self.tabs.select(self.sign_tab)
        self.clear_challenge()
        self.progress.stop()
        self.label(self.challenge, label, 11, bold=True).pack(anchor='w', pady=(3, 5))
        field = ttk.Entry(self.challenge, show='•' if secret else '', font=('Microsoft YaHei UI', 11))
        field.pack(fill='x')
        field.focus_set()
        def submit():
            value = field.get().strip() if code else field.get()
            if not value or code and not re.fullmatch(r'\d{6}', value):
                return
            field.delete(0, 'end')
            self.send(value)
        ttk.Button(self.challenge, text='继续', command=submit).pack(anchor='w', pady=6)
        field.bind('<Return>', lambda _: submit())
        self.root.after_idle(lambda: self.sign_scroll.yview_moveto(1))

    def send(self, value):
        try:
            self.task.submit(value)
            self.clear_challenge()
            self.status.set('正在验证，请稍候…')
            self.progress.start(12)
        except (OSError, RuntimeError, ValueError):
            self.status.set('授权进程已结束，可以重新开始。')

    def drain(self):
        try:
            while True:
                self.handle(*self.events.get_nowait())
        except queue.Empty:
            pass
        self.root.after(100, self.drain)

    def handle(self, name, detail):
        if name == 'status':
            self.status.set(detail)
        elif name == 'github_code':
            self.tabs.select(self.sign_tab)
            self.clear_challenge()
            self.label(self.challenge, '在 GitHub 授权页输入：' + detail, 14, bold=True).pack(anchor='w', pady=6)
            ttk.Button(self.challenge, text='打开 GitHub 授权页', command=lambda: webbrowser.open('https://github.com/login/device')).pack(anchor='w')
            self.status.set('请在浏览器中登录自己的 GitHub 账号并确认授权。')
        elif name == 'github_ready':
            self.github.set('已登录：' + detail['login'])
            self.clear_challenge()
            self.status.set('GitHub 已连接，可以开始 Apple 授权。')
        elif name == 'devices':
            self.devices = detail
            self.device_box.configure(values=[d['name'] + ' · ' + d['udid'][-6:] for d in detail])
            if detail:
                self.device_box.current(0)
                self.select_device()
                self.status.set('已读取设备。')
            else:
                self.status.set('尚未发现 USB 设备。请连接、解锁并信任电脑后重新读取。')
        elif name == 'password':
            self.status.set('请在本机输入 Apple 账号密码。')
            self.input_challenge('Apple 账号密码', secret=True)
        elif name in ('device_code', 'sms_code', 'voice_code'):
            self.status.set('请查看 Apple 设备或短信中的验证码。')
            self.input_challenge('六位验证码', code=True)
        elif name == 'method':
            self.clear_challenge()
            self.progress.stop()
            self.label(self.challenge, '选择验证方式', 11, bold=True).pack(anchor='w')
            for value, label in detail or []:
                ttk.Button(self.challenge, text=label, command=lambda v=value: self.send(v)).pack(side='left', padx=(0, 8), pady=8)
        elif name == 'preparing_device':
            self.status.set('正在建立独立的设备认证…')
        elif name == 'phase':
            phases = {'resume_session': '正在继续上次的加密登录会话…',
                      'save_session': '正在加密保存 Apple 登录会话…',
                      'personal_team': '正在读取免费个人开发团队…',
                      'register_device': '正在准备设备注册…', 'register_app': '正在准备应用标识…',
                      'certificate': '正在准备个人签名证书…',
                      'provisioning_profile': '正在申请设备描述文件…',
                      'encrypt_state': '正在加密保存签名状态…'}
            if detail in phases:
                self.status.set(phases[detail])
        elif name in ('authorized', 'cloud'):
            self.clear_challenge()
            self.status.set('本机授权已完成，正在等待 GitHub 首次签名和校验；请保持窗口打开。')
        elif name == 'ipa_ready':
            path = Path(detail).resolve()
            if path.is_relative_to((data_dir() / 'downloads').resolve()) and path.is_file():
                self.ipa = path
                self.package.set(str(path))
                self.tabs.select(self.install_tab)
                self.status.set('签名 IPA 已下载，可以安装到所选设备。')
        elif name == 'installed':
            self.status.set('设备已报告安装完成。请在 iPhone / iPad 上完成首次打开设置。')
            self.tabs.select(self.install_tab)
            self.show_first_launch()
        elif name in ('download_progress', 'install_progress'):
            self.progress.stop()
            self.progress.configure(mode='determinate', value=detail.get('percent', 0))
            phase = '正在下载组件' if name == 'download_progress' else ('正在传输安装包' if detail.get('stage') == 'transfer' else '正在设备上安装')
            self.status.set(phase + ' · ' + str(detail.get('percent', 0)) + '%')
        elif name in ('error', 'error_code'):
            self.error = detail
            self.status.set(ERRORS.get(detail, '操作未完成，请检查网络和当前步骤后重试。') + '（' + str(detail) + '）')
        elif name in ('done', 'cancelled'):
            self.set_busy(False)
            self.clear_challenge()
            clean_login_temporary()
            if name == 'cancelled':
                self.status.set('已停止当前任务。若设备已经开始安装，请等待设备处理完成后再操作。')
            elif detail['code'] and not self.error:
                self.status.set('操作未完成，可以检查当前步骤后重试。')
            if self.pending_sign:
                self.pending_sign = False
                if name == 'done' and detail['code'] == 0:
                    self.root.after(100, self.sign)

    def cancel(self):
        if self.task:
            self.status.set('正在停止当前任务…')
            self.cancel_button.configure(state='disabled')
            self.task.cancel()

    def open_downloads(self):
        folder = self.ipa.parent if self.ipa else data_dir() / 'downloads'
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def save_ipa(self):
        if not self.ipa or not self.ipa.is_file():
            messagebox.showinfo('还没有安装包', '请先下载或选择 IPA。', parent=self.root)
            return
        value = filedialog.asksaveasfilename(parent=self.root, initialfile=self.ipa.name, defaultextension='.ipa', filetypes=[('iOS 安装包', '*.ipa')])
        if value:
            import shutil
            shutil.copy2(self.ipa, value)

    def export_sources(self):
        import shutil
        folder = data_dir() / 'source-and-notices'
        folder.mkdir(exist_ok=True)
        for name in ('source.zip', 'NOTICES.txt'):
            path = ASSETS / name
            if path.is_file():
                shutil.copy2(path, folder / name)
        os.startfile(str(folder))

    def close(self):
        if self.busy and not messagebox.askyesno('结束当前任务', '当前任务仍在进行，确定要停止并关闭吗？', parent=self.root):
            return
        if self.busy:
            self.cancel()
        self.root.destroy()


def main(initial_ipa=None):
    import ctypes
    import hashlib
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    identity = hashlib.sha256(str(data_dir()).lower().encode()).hexdigest()[:24]
    handle = kernel.CreateMutexW(None, 0, 'Local\\LumaPocketInstaller-' + identity)
    if ctypes.get_last_error() == 183:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)
        messagebox.showinfo('安装助手已打开', '请使用已经打开的 LumaPocket 安装助手窗口。')
        return
    clean_login_temporary()
    root = tk.Tk()
    Window(root, initial_ipa=initial_ipa)
    try:
        root.mainloop()
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)
