#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Selenium-Only 12306 WeChat Bot · 2025-07-03
————————————————————————————————————————————
• ✅ 12306 查询 = Selenium • 多模态 AI 回复
• ✅ 浏览器常驻复用    • UI 主题 ttk（自定义）
————————————————————————————————————————————
依赖：pip install wxauto selenium webdriver-manager pillow
"""

import os, sys, json, queue, time, threading, traceback, ai
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, Optional

import urllib3
from wxauto import WeChat
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText
from PIL import Image, ImageTk          # ← 新增

# ——— 常量 ——— #
APP_NAME        = "微信 AI Bot"
BASE_DIR      = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
SETTINGS_FILE = BASE_DIR / "settings.json"

STATION_FILE    = BASE_DIR / ".1.json"
BACKGROUND      = BASE_DIR / "background.png"       # ← 背景 PNG，None=不启用
HEADLESS        = True
LOG_TRIM_LINES  = 4_000
IMAGE_TIMEOUT   = 10       # s
WAIT_INTERVAL   = 0.1      # s
CHROME_BINARY   = None

# ——— 环境初始化 ——— #
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout.reconfigure(encoding="utf-8")

# ——— 站点码表 ——— #
with open(STATION_FILE, encoding="utf-8") as f:
    _station_map = {i["station_name"]: i["station_telecode"]
                    for i in json.load(f).get("Sheet1", [])}
def get_station_code(name: str) -> str:
    return _station_map.get(name, "")

# ————————————————— Selenium 单例 ————————————————— #
class _Chrome:
    """用一次取一次，cookie 自动保持。_Chrome.get().fetch_json(...) → dict"""
    _inst: Optional["_Chrome"] = None
    def __init__(self):
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from webdriver_manager.chrome import ChromeDriverManager

        opts = Options()
        if HEADLESS:
            opts.add_argument("--headless=new")
            opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-infobars")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--log-level=3")
        opts.add_argument("--disable-dev-shm-usage")
        if CHROME_BINARY:
            opts.binary_location = CHROME_BINARY

        self._drv = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=opts
        )
        self._drv.set_page_load_timeout(15)
        self._drv.get("https://kyfw.12306.cn/otn/leftTicket/init")  # 建立 cookie

    @classmethod
    def get(cls) -> "_Chrome":
        if cls._inst is None:
            cls._inst = _Chrome()
        return cls._inst

    def fetch_json(self, dep: str, arr: str, date: str) -> dict:
        from selenium.webdriver.common.by import By
        url = ( "https://kyfw.12306.cn/otn/leftTicket/query?"
                f"leftTicketDTO.train_date={date}"
                f"&leftTicketDTO.from_station={dep}"
                f"&leftTicketDTO.to_station={arr}&purpose_codes=ADULT" )
        self._drv.get(url)
        body = self._drv.find_element(By.TAG_NAME, "body").text
        return json.loads(body)

    def quit(self):
        try: self._drv.quit()
        except Exception: pass

# —————————————— 业务函数（与 UI 无关） —————————————— #
def _fetch(dep:str, arr:str, date:str)->dict:
    return _Chrome.get().fetch_json(dep, arr, date)

def query_all_tickets(dep:str, arr:str)->str:
    dep_c, arr_c = get_station_code(dep), get_station_code(arr)
    if not dep_c or not arr_c:
        return f"❌ 未找到站名 {dep}/{arr}"
    date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        data = _fetch(dep_c, arr_c, date)
    except Exception as e:
        return f"⚠️ 查询失败：{e}"
    res, mp = data["data"]["result"], data["data"]["map"]
    if not res: return "🚫 暂无余票"

    def fmt(r:str):
        p=r.split("|")
        return (f"🚄{p[3]} {mp.get(p[6],p[6])}->{mp.get(p[7],p[7])} "
                f"{p[8]}-{p[9]} 历时{p[10]}\n"
                f"商:{p[32]} ①:{p[31]} ②:{p[30]} 软:{p[23]} "
                f"硬卧:{p[28]} 硬座:{p[29]} 无座:{p[26]}")
    return "\n\n".join(map(fmt, res))

def query_schedule(code:str, dep:str, arr:str)->str:
    dep_c, arr_c = get_station_code(dep), get_station_code(arr)
    if not dep_c or not arr_c:
        return f"❌ 未找到站名 {dep}/{arr}"
    date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        data = _fetch(dep_c, arr_c, date)
    except Exception as e:
        return f"⚠️ 查询失败：{e}"
    for r in data["data"]["result"]:
        p=r.split("|")
        if p[3].upper()==code.upper():
            return (f"🚅{p[3]} {dep}->{arr}\n"
                    f"开 {p[8]}  到 {p[9]}  历时 {p[10]}")
    return f"🚫 未找到车次 {code}"

query_tickets = query_schedule  # 兼容旧接口

# ———————————————— Tk 组件增强 ———————————————— #
class PlaceholderEntry(ttk.Entry):
    """灰色占位文本（FocusIn 自动清空）"""
    def __init__(self, master=None, placeholder:str="", color:str="#999", **kw):
        super().__init__(master, **kw)
        self._ph_text, self._ph_color = placeholder, color
        self._default_fg = self.cget("foreground")
        self.bind("<FocusIn>", self._clear)
        self.bind("<FocusOut>", self._show)
        self._show()

    def _show(self, *_):
        if not self.get():
            self.insert(0, self._ph_text)
            self.configure(foreground=self._ph_color)

    def _clear(self, *_):
        if self.cget("foreground")==self._ph_color:
            self.delete(0,"end")
            self.configure(foreground=self._default_fg)

# ——————————————— 主应用 ——————————————— #
class WeChatBotApp:
    def __init__(self):
        self.wx=None; self.running=False
        self.listen_list=[]; self.mapping_list=[]
        self._last_imgs:Dict[str,Dict[str,Any]]={}
        self.log_q:queue.Queue[str]=queue.Queue()

        self.root=tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("480x680")        # 更舒适的默认窗口
        self.root.minsize(420,560)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # ——— 主题配色 ——— #
        style=ttk.Style()
        style.theme_use("clam")
        style.configure("TButton", font=("Segoe UI",10,"bold"), padding=6)
        style.configure("TLabel",  font=("Segoe UI",10),   background="#ffffff")
        style.configure("TEntry",  font=("Segoe UI",10))
        style.configure("TListbox", font=("Segoe UI",10))

        # ——— 背景图 ——— #
        if BACKGROUND and Path(BACKGROUND).exists():
            self._orig_bg = Image.open(BACKGROUND)
            self._bg_img  = ImageTk.PhotoImage(self._orig_bg)
            self._bg_lbl  = tk.Label(self.root, image=self._bg_img, borderwidth=0)
            self._bg_lbl.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.root.bind("<Configure>", self._resize_bg)  # 窗口变动时自适应

        # ——— 顶部菜单 ——— #
        menubar = tk.Menu(self.root)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self._show_help)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.root.config(menu=menubar)

        # ——— UI 组件 ——— #
        ttk.Label(self.root,text="监听好友（每行一个）").pack(anchor="w", padx=8, pady=(8,2))
        self.t_names = tk.Text(self.root, height=3, font=("Consolas",10))
        self.t_names.pack(fill="x", padx=8)

        self.ai = tk.StringVar()
        ttk.Label(self.root,text="AI 名称（@Ta）").pack(anchor="w", padx=8, pady=(6,2))
        ttk.Entry(self.root, textvariable=self.ai).pack(fill="x", padx=8)

        frm = ttk.Frame(self.root); frm.pack(fill="x", padx=8, pady=8)
        self.e_who = PlaceholderEntry(frm, placeholder="指定好友 (可留空)", width=10)
        self.e_kw  = PlaceholderEntry(frm, placeholder="关键词*", width=14)
        self.e_rp  = PlaceholderEntry(frm, placeholder="自动回复*", width=18)
        self.e_who.grid(row=0,column=0,padx=2); self.e_kw.grid(row=0,column=1,padx=2)
        self.e_rp.grid(row=0,column=2,padx=2)
        ttk.Button(frm,text="添加映射",command=self.add_map).grid(row=0,column=3,padx=4, ipadx=4)

        self.lb_map = tk.Listbox(self.root, height=4)
        self.lb_map.pack(fill="x", padx=8)

        bf = ttk.Frame(self.root); bf.pack(fill="x", padx=8, pady=8)
        self.btn_start = ttk.Button(bf,text="▶ 启动监听",command=self.start)
        self.btn_stop  = ttk.Button(bf,text="■ 停止",command=self.stop,state="disabled")
        self.btn_start.pack(side="left",expand=True,fill="x",padx=(0,4))
        self.btn_stop .pack(side="left",expand=True,fill="x",padx=(4,0))

        ttk.Label(self.root,text="日志").pack(anchor="w", padx=8)
        self.log = ScrolledText(self.root, state="disabled", height=12, font=("Consolas",9))
        self.log.pack(fill="both", expand=True, padx=8, pady=(0,8))
        self.root.after(100, self._flush_log)

        self._load()   # 读入本地设置文件

    # ——— 背景自适应缩放 ——— #
    def _resize_bg(self, event):
        if not BACKGROUND: return
        if event.width < 50 or event.height < 50: return
        img = self._orig_bg.resize((event.width,event.height), Image.LANCZOS)
        self._bg_img = ImageTk.PhotoImage(img)
        self._bg_lbl.configure(image=self._bg_img)

    # ——— 菜单帮助弹窗 ——— #
    def _show_help(self):
        messagebox.showinfo("使用说明",
            "· 监听好友：每行输入一个微信昵称；会自动开始截图保存（存放于 wxauto 缺省路径）。\n"
            "· AI 名称：让好友在消息里 @此名字，才能触发 AI 回答。\n"
            "· 关键词映射：小型自动回复；“指定好友”留空表示对所有监听对象生效。\n"
            "· 图片 + @AI + 提问，可触发多模态推理（需自备 ai.chat_multimodal）。\n"
            "· 12306 相关：\n"
            "    车次 G123 上海 南京   —— 查询当天 G123 时间\n"
            "    车票 上海 南京        —— 查询明日所有车次余票")

    # ——— 设置持久化 ——— #
    def _load(self):
        if not SETTINGS_FILE.exists(): return
        try:
            d=json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self.t_names.insert("1.0", "\n".join(d.get("listen",[])))
            self.ai.set(d.get("ai_name",""))
            for w,k,r in d.get("maps",[]):
                self.mapping_list.append((w,k,r))
                self.lb_map.insert("end", f"{w or '*'} | {k} → {r}")
        except Exception as e:
            self._log(f"⚠️ 读取设置失败：{e}")

    def _save(self):
        BASE_DIR.mkdir(exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps({
            "listen": self.listen_list,
            "ai_name": self.ai.get(),
            "maps": self.mapping_list
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # ——— 日志输出 ——— #
    def _log(self, s:str):
        self.log_q.put(s)

    def _flush_log(self):
        try:
            while True:
                line=self.log_q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", line+"\n")
                if int(float(self.log.index("end"))) > LOG_TRIM_LINES:
                    self.log.delete("1.0","3.0")
                self.log.configure(state="disabled")
                self.log.yview("end")
        except queue.Empty:
            pass
        finally:
            self.root.after(120, self._flush_log)

    # ——— 映射 & 启停 ——— #
    def add_map(self):
        w,k,r = (self.e_who.get().strip(), self.e_kw.get().strip(), self.e_rp.get().strip())
        if not k or not r or k.startswith("关键词"):
            messagebox.showwarning("提示","关键词 / 回复 不能为空")
            return
        self.mapping_list.append((w,k,r))
        self.lb_map.insert("end", f"{w or '*'} | {k} → {r}")
        for e in (self.e_who,self.e_kw,self.e_rp): e.delete(0,"end")
        self._save()

    def start(self):
        self.listen_list=[n.strip() for n in self.t_names.get("1.0","end").splitlines() if n.strip()]
        if not self.listen_list:
            self._log("❌ 请填写监听好友")
            return
        try:
            self.wx = WeChat(); self.wx.GetSessionList()
        except Exception as e:
            messagebox.showerror("初始化失败", f"无法启动 wxauto：{e}")
            return
        for n in self.listen_list:
            self.wx.AddListenChat(who=n, savepic=True)
            self._log(f"🔎 监听 {n}")
        self.running=True
        threading.Thread(target=self._loop,daemon=True).start()
        self.btn_start["state"]="disabled"
        self.btn_stop ["state"]="normal"
        self._save()

    def stop(self):
        self.running=False
        self.btn_start["state"]="normal"
        self.btn_stop ["state"]="disabled"
        self._log("🛑 已停止")
        self._save()

    # ——— 主循环 ——— #
    def _loop(self):
        ai_tag=f"@{self.ai.get().strip()}"
        while self.running:
            try:
                msgs=self.wx.GetListenMessage()
                for chat,lst in msgs.items():
                    who=chat.who
                    for m in lst:
                        txt=m.content.strip()

                        # 图片：记录时间戳，用于多模态
                        if m.type in ("img","pic","image") or (
                            os.path.isfile(txt) and txt.lower().endswith((".jpg",".png",".jpeg",".bmp"))):
                            self._last_imgs[who]={"path":txt,"time":time.time()}
                            self._log(f"[{who}] 📷 {txt}"); continue

                        self._log(f"[{who}]({m.type}) {txt}")

                        # —— 12306 查询 —— #
                        if m.type=="friend" and ai_tag in txt:
                            cmd = txt.replace(ai_tag,"").strip().split()
                            if txt.startswith("车次") and len(cmd)==3:
                                ans=query_tickets(cmd[0],cmd[1],cmd[2]); chat.SendMsg(ans); continue
                            if txt.startswith("车票") and len(cmd)==2:
                                ans=query_all_tickets(cmd[0],cmd[1]); chat.SendMsg(ans); continue

                        # —— AI 回复 —— #
                        if m.type=="friend" and ai_tag in txt:
                            q = txt.replace(ai_tag,"").strip()
                            img=self._last_imgs.get(who)
                            if img and time.time()-img["time"]<=IMAGE_TIMEOUT:
                                res=ai.chat_multimodal(who,[{"image":img["path"]},{"text":q}])
                                del self._last_imgs[who]
                            else:
                                res=ai.chat(who,q)
                            chat.SendMsg(res); self._log(f"↪️ AI: {res}"); continue

                        # —— 关键词映射 —— #
                        for mw,mk,mr in self.mapping_list:
                            if mk in txt and (not mw or mw==who) and m.type=="friend":
                                chat.SendMsg("[自动]"+mr)
                                self._log(f"↪️ 自动: {mr}")
                                break
                time.sleep(WAIT_INTERVAL)
            except Exception as e:
                self._log(f"⚠️ 异常: {e}\n{traceback.format_exc()}")
                time.sleep(3)

    # ——— 关闭时清理 ——— #
    def on_close(self):
        self.running=False
        try: _Chrome.get().quit()
        except Exception: pass
        self._save()
        self.root.destroy()

    def run(self): self.root.mainloop()

# ———————————————— 主入口 ———————————————— #
if __name__ == "__main__":
    try:
        WeChatBotApp().run()
    except Exception:
        traceback.print_exc()
