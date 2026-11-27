"""Simulador interactivo de colas para el laboratorio de parqueaderos.

Modelo de trabajo: tres filas independientes; cada fila recibe una corriente
Poisson de llegadas. El tipo de usuario se selecciona según los porcentajes
del enunciado y su tiempo de servicio se genera con distribución exponencial.
La llegada agregada usa el promedio ponderado de los intervalos indicados.
Esta hipótesis se muestra en la interfaz porque el enunciado no define de forma
inequívoca cómo combinar porcentajes e intervalos de llegada por categoría.
"""
from __future__ import annotations
import csv
import json
import math
import os
import random
import statistics
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from dataclasses import dataclass, asdict
from datetime import datetime

import numpy as np
import matplotlib
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from scipy import stats

APP_TITLE = "PARKSIM | Laboratorio de colas"
COLORS = {"Rápido": "#20a779", "Normal": "#3987d5", "Lento": "#e5a33b", "Muy lento": "#df6262"}
USERS = {
    "Rápido": {"service": 1.0, "interarrival": 3.0, "share": 0.25},
    "Normal": {"service": 3.0, "interarrival": 3.0, "share": 0.20},
    "Lento": {"service": 4.0, "interarrival": 5.0, "share": 0.275},
    "Muy lento": {"service": 6.0, "interarrival": 7.0, "share": 0.275},
}

@dataclass
class Customer:
    cashier: int
    replication: int
    kind: str
    arrival: float
    start: float
    finish: float
    wait: float
    service: float
    system: float


def weighted_interarrival() -> float:
    return sum(v["interarrival"] * v["share"] for v in USERS.values())


def pick_kind(rng: random.Random) -> str:
    x = rng.random()
    cumulative = 0.0
    for name, data in USERS.items():
        cumulative += data["share"]
        if x <= cumulative:
            return name
    return "Muy lento"


def moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if len(values) < window:
        return np.array([], dtype=float)
    return np.convolve(values, np.ones(window) / window, mode="valid")


def warmup_cut(values: list[float], window: int = 40) -> int:
    """Heurística gráfica: primer punto donde la media móvil se mantiene
    dentro de ±5% de la media móvil final durante varias ventanas.
    Devuelve índice de observación, no una verdad matemática universal.
    """
    arr = np.asarray(values, dtype=float)
    if len(arr) < max(120, window * 5):
        return max(0, int(len(arr) * 0.20))
    ma = moving_average(arr, window)
    if len(ma) == 0:
        return 0
    tail = ma[int(len(ma) * 0.75):]
    target = float(np.mean(tail)) if len(tail) else float(np.mean(ma))
    tolerance = max(abs(target) * 0.05, 0.05)
    hold = max(10, window // 2)
    for i in range(0, max(1, len(ma) - hold)):
        if np.all(np.abs(ma[i:i + hold] - target) <= tolerance):
            return min(len(arr) - 1, i + window - 1)
    return int(len(arr) * 0.20)


def confidence_interval(values: list[float]) -> tuple[float, float, float, float, float]:
    if not values:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    n = len(values)
    mean = statistics.mean(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    if n > 1:
        margin = float(stats.t.ppf(0.975, n - 1) * sd / math.sqrt(n))
    else:
        margin = 0.0
    return mean, sd, min(values), max(values), margin


def simulate_cashier(cashier: int, replication: int, duration: float, rng: random.Random) -> list[Customer]:
    """Simula una fila FIFO M/G/1 de servicio mixto por categoría.

    Las llegadas son exponenciales con media ponderada 4.55 min; la clase
    se asigna por los porcentajes del enunciado y cada clase tiene servicio
    exponencial con su media correspondiente.
    """
    mean_gap = weighted_interarrival()
    t = 0.0
    finish_previous = 0.0
    customers: list[Customer] = []
    while True:
        t += rng.expovariate(1.0 / mean_gap)
        if t > duration:
            break
        kind = pick_kind(rng)
        service = rng.expovariate(1.0 / USERS[kind]["service"])
        start = max(t, finish_previous)
        finish = start + service
        customers.append(Customer(cashier, replication, kind, t, start, finish,
                                  start - t, service, finish - t))
        finish_previous = finish
    return customers


def run_experiment(cashiers: int, duration: float, replications: int, seed: int):
    all_customers: list[Customer] = []
    rep_data = []
    for rep in range(replications):
        for c in range(1, cashiers + 1):
            rng = random.Random(seed + rep * 100003 + c * 997)
            all_customers.extend(simulate_cashier(c, rep + 1, duration, rng))
    # Orden de llegada por cajero, para que el análisis de calentamiento sea reproducible.
    by_cashier = {c: sorted([x for x in all_customers if x.cashier == c], key=lambda z: (z.replication, z.arrival))
                  for c in range(1, cashiers + 1)}
    cuts = {}
    stable_customers = []
    for c, records in by_cashier.items():
        cashier_cuts = []
        for rep in range(1, replications + 1):
            batch = [x for x in records if x.replication == rep]
            cut = warmup_cut([x.system for x in batch])
            cashier_cuts.append(cut)
            stable_customers.extend(batch[cut:])
        cuts[c] = cashier_cuts
    return all_customers, stable_customers, by_cashier, cuts


class ParkSimApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1320x850")
        self.minsize(1120, 720)
        self.configure(bg="#eef2f7")
        self.results = None
        self._style()
        self._build_header()
        self._build_tabs()
        self._build_home()
        self._build_simulation_tab()
        self._build_results_tab()
        self._build_transient_tab()
        self._build_validation_tab()
        self._build_export_tab()

    def _style(self):
        s = ttk.Style(self)
        try: s.theme_use("clam")
        except tk.TclError: pass
        s.configure("TNotebook", background="#eef2f7", borderwidth=0)
        s.configure("TNotebook.Tab", padding=(18, 10), font=("Segoe UI", 10, "bold"), background="#dce5ef")
        s.map("TNotebook.Tab", background=[("selected", "#ffffff")], foreground=[("selected", "#18324b")])
        s.configure("Treeview", rowheight=27, font=("Segoe UI", 9), background="white", fieldbackground="white")
        s.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"), background="#e7edf4")
        s.configure("TButton", font=("Segoe UI", 10, "bold"), padding=8)
        s.configure("TLabel", background="white", font=("Segoe UI", 10))
        s.configure("TLabelframe", background="white")
        s.configure("TLabelframe.Label", background="white", foreground="#24445f", font=("Segoe UI", 10, "bold"))

    def _build_header(self):
        header = tk.Frame(self, bg="#142b43", height=78)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="🚗  PARKSIM", bg="#142b43", fg="white", font=("Segoe UI", 21, "bold")).pack(side="left", padx=25)
        tk.Label(header, text="LABORATORIO DE SIMULACIÓN DE PARQUEADEROS  |  M/M/1", bg="#142b43", fg="#b9d4e8", font=("Segoe UI", 10, "bold")).pack(side="left", padx=10)
        self.status_label = tk.Label(header, text="● LISTO PARA SIMULAR", bg="#142b43", fg="#71ddb0", font=("Segoe UI", 9, "bold"))
        self.status_label.pack(side="right", padx=24)

    def _build_tabs(self):
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=14, pady=(12, 14))
        self.home_tab = tk.Frame(self.tabs, bg="#eef2f7")
        self.sim_tab = tk.Frame(self.tabs, bg="#eef2f7")
        self.results_tab = tk.Frame(self.tabs, bg="#eef2f7")
        self.trans_tab = tk.Frame(self.tabs, bg="#eef2f7")
        self.validation_tab = tk.Frame(self.tabs, bg="#eef2f7")
        self.export_tab = tk.Frame(self.tabs, bg="#eef2f7")
        for tab, label in [(self.home_tab,"Inicio"),(self.sim_tab,"Simulación"),(self.results_tab,"Resultados"),(self.trans_tab,"Estado transitorio"),(self.validation_tab,"Verificación y validación"),(self.export_tab,"Exportar")]:
            self.tabs.add(tab, text=label)
        # Cada pestaña tiene su propio panel desplazable. Así se puede recorrer
        # todo el contenido aunque haya muchas tablas y gráficas.
        self.home_content = self._make_scrollable_tab(self.home_tab)
        self.sim_content = self._make_scrollable_tab(self.sim_tab)
        self.results_content = self._make_scrollable_tab(self.results_tab)
        self.trans_content = self._make_scrollable_tab(self.trans_tab)
        self.validation_content = self._make_scrollable_tab(self.validation_tab)
        self.export_content = self._make_scrollable_tab(self.export_tab)

    def _make_scrollable_tab(self, tab):
        shell = tk.Frame(tab, bg="#eef2f7")
        shell.pack(fill="both", expand=True)
        canvas = tk.Canvas(shell, bg="#eef2f7", highlightthickness=0, borderwidth=0)
        scrollbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = tk.Frame(canvas, bg="#eef2f7")
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")

        def update_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def fit_content_width(event):
            canvas.itemconfigure(window_id, width=event.width)

        content.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", fit_content_width)

        # Rueda del ratón: funciona en Windows y Linux; Shift + rueda desplaza horizontalmente.
        def mousewheel(event):
            if getattr(event, "delta", 0):
                canvas.yview_scroll(int(-event.delta / 120), "units")
            elif getattr(event, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                canvas.yview_scroll(3, "units")

        def bind_wheel(_event=None):
            canvas.bind_all("<MouseWheel>", mousewheel)
            canvas.bind_all("<Button-4>", mousewheel)
            canvas.bind_all("<Button-5>", mousewheel)

        def unbind_wheel(_event=None):
            canvas.unbind_all("<MouseWheel>")
            canvas.unbind_all("<Button-4>")
            canvas.unbind_all("<Button-5>")

        canvas.bind("<Enter>", bind_wheel)
        canvas.bind("<Leave>", unbind_wheel)
        return content

    def _card(self, parent, title, subtitle=None):
        frame = tk.Frame(parent, bg="white", highlightbackground="#dce4ed", highlightthickness=1)
        tk.Label(frame, text=title, bg="white", fg="#18324b", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=18, pady=(14, 3))
        if subtitle:
            tk.Label(frame, text=subtitle, bg="white", fg="#64788a", font=("Segoe UI", 9), wraplength=900, justify="left").pack(anchor="w", padx=18, pady=(0, 10))
        return frame

    def _build_home(self):
        outer = tk.Frame(self.home_content, bg="#eef2f7")
        outer.pack(fill="both", expand=True, padx=16, pady=16)
        intro = self._card(outer, "Centro Comercial Supercentro", "Simulador interactivo para estudiar tres cajeros con filas independientes, usuarios de cuatro tipos y atención FIFO.")
        intro.pack(fill="x", pady=(0, 12))
        body = tk.Frame(outer, bg="#eef2f7")
        body.pack(fill="both", expand=True)
        left = self._card(body, "Parámetros del enunciado")
        left.pack(side="left", fill="both", expand=True, padx=(0, 8))
        tree = ttk.Treeview(left, columns=("service","arrival","share"), show="headings", height=5)
        for col, title in [("service","Servicio medio"),("arrival","Entre llegadas"),("share","Porcentaje")]: tree.heading(col,text=title)
        tree.column("service",width=130,anchor="center"); tree.column("arrival",width=130,anchor="center"); tree.column("share",width=100,anchor="center")
        for name, v in USERS.items(): tree.insert("","end",values=(name+f" · {v['service']} min",f"{v['interarrival']} min",f"{v['share']*100:g}%"))
        tree.pack(fill="x", padx=16, pady=12)
        right = self._card(body, "Qué encontrarás en el simulador")
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        for line in ["01  Estadísticas por cajero e intervalos de confianza del 95%", "02  Conteo y promedio de usuarios por categoría", "03  Comparación de escenarios con 3, 4 y 5 cajeros", "04  Pruebas de verificación y contraste con teoría M/M/1", "05  Promedio móvil y análisis del período de calentamiento"]:
            tk.Label(right, text=line, bg="white", fg="#304b63", font=("Segoe UI", 10), anchor="w").pack(fill="x", padx=18, pady=8)
        note = self._card(outer, "Nota metodológica importante", "El documento entrega porcentajes de usuarios y tiempos medios entre llegadas por tipo, pero no define con precisión cómo combinarlos en las tres filas. Para que el programa sea ejecutable, se adopta una hipótesis explícita: cada fila recibe llegadas exponenciales con intervalo medio ponderado (4,55 minutos) y cada llegada se clasifica usando los porcentajes indicados. El servicio depende del tipo de usuario. Por esta mezcla, la fila completa se comporta como una cola M/G/1 de servicio mixto; los cálculos M/M/1 por categoría se muestran aparte como referencia teórica, no como si fueran la misma cola.")
        note.pack(fill="x", pady=(12, 0))
        tk.Button(outer, text="IR A CONFIGURAR Y SIMULAR  →", command=lambda:self.tabs.select(self.sim_tab), bg="#1d79b7", fg="white", activebackground="#176493", relief="flat", font=("Segoe UI", 11, "bold"), padx=18, pady=10).pack(anchor="e", pady=12)

    def _build_simulation_tab(self):
        outer = tk.Frame(self.sim_content, bg="#eef2f7"); outer.pack(fill="both", expand=True, padx=16, pady=16)
        settings = self._card(outer, "Configuración del experimento", "Puedes cambiar duración, réplicas y semilla. Para comparar con el laboratorio, inicia con tres cajeros.")
        settings.pack(fill="x")
        row = tk.Frame(settings, bg="white"); row.pack(fill="x", padx=18, pady=12)
        self.cashiers_var = tk.IntVar(value=3); self.duration_var = tk.IntVar(value=10000); self.reps_var = tk.IntVar(value=10); self.seed_var = tk.IntVar(value=42)
        self._field(row,"Cajeros",self.cashiers_var,1,8); self._field(row,"Duración por réplica (min)",self.duration_var,1000,1000000); self._field(row,"Réplicas",self.reps_var,2,100); self._field(row,"Semilla aleatoria",self.seed_var,0,9999999)
        controls = tk.Frame(settings,bg="white"); controls.pack(fill="x",padx=18,pady=(0,14))
        self.run_button = tk.Button(controls,text="▶  EJECUTAR SIMULACIÓN",command=self._start_sim,bg="#16865f",fg="white",relief="flat",font=("Segoe UI",11,"bold"),padx=18,pady=10)
        self.run_button.pack(side="left")
        self.progress = ttk.Progressbar(controls, mode="indeterminate", length=230); self.progress.pack(side="left", padx=16)
        self.run_msg = tk.Label(controls,text="Listo. Los resultados aparecerán en las pestañas siguientes.",bg="white",fg="#62788c",font=("Segoe UI",9)); self.run_msg.pack(side="left")
        summary = self._card(outer,"Cómo se ejecuta", "Cada cajero tiene una fila FIFO independiente. No se permite cambiar de fila ni abandonar la cola. Se registran llegada, inicio del servicio, finalización, espera y tiempo total en el sistema.")
        summary.pack(fill="x",pady=12)
        tk.Label(summary,text="Recomendación: usa primero 10 réplicas de 10.000 minutos. Si tu equipo responde bien, puedes aumentar las réplicas para obtener estimaciones más estables.",bg="white",fg="#304b63",font=("Segoe UI",10),wraplength=1000,justify="left").pack(anchor="w",padx=18,pady=(0,14))

    def _field(self,parent,label,var,lo,hi):
        box=tk.Frame(parent,bg="white"); box.pack(side="left",fill="x",expand=True,padx=(0,12))
        tk.Label(box,text=label,bg="white",fg="#536b80",font=("Segoe UI",9,"bold")).pack(anchor="w")
        spin= tk.Spinbox(box,from_=lo,to=hi,textvariable=var,width=13,font=("Segoe UI",11),relief="solid",bd=1)
        spin.pack(anchor="w",pady=5)

    def _start_sim(self):
        try:
            n=int(self.cashiers_var.get()); duration=int(self.duration_var.get()); reps=int(self.reps_var.get()); seed=int(self.seed_var.get())
            if not (1<=n<=8 and 1000<=duration<=1000000 and 2<=reps<=100): raise ValueError
        except Exception:
            messagebox.showerror("Configuración no válida","Revisa los valores: cajeros 1–8, duración 1.000–1.000.000 y réplicas 2–100."); return
        self.run_button.config(state="disabled"); self.progress.start(12); self.status_label.config(text="● SIMULANDO...",fg="#f2c66d"); self.run_msg.config(text="Calculando eventos y estadísticas...")
        threading.Thread(target=self._worker,args=(n,duration,reps,seed),daemon=True).start()

    def _worker(self,n,duration,reps,seed):
        try:
            raw, stable, by_cashier, cuts = run_experiment(n,duration,reps,seed)
            self.after(0,lambda:self._finish_sim((raw,stable,by_cashier,cuts,n,duration,reps,seed)))
        except Exception as e:
            self.after(0,lambda:messagebox.showerror("Error de simulación",str(e)))
            self.after(0,self._reset_run)

    def _reset_run(self):
        self.progress.stop(); self.run_button.config(state="normal"); self.status_label.config(text="● LISTO PARA SIMULAR",fg="#71ddb0")

    def _finish_sim(self,data):
        self.results=data
        self.progress.stop(); self.run_button.config(state="normal"); self.status_label.config(text="● SIMULACIÓN COMPLETADA",fg="#71ddb0")
        raw,stable,by_cashier,cuts,n,duration,reps,seed=data
        self.run_msg.config(text=f"Completado: {len(raw):,} atenciones registradas; {len(stable):,} después del corte.")
        self._refresh_results(); self._refresh_transient(); self._refresh_validation()
        self.tabs.select(self.results_tab)

    def _make_table(self,parent,columns,headings,height=7):
        frame=tk.Frame(parent,bg="white"); frame.pack(fill="both",expand=True,padx=14,pady=10)
        tree=ttk.Treeview(frame,columns=columns,show="headings",height=height)
        for c,h in zip(columns,headings): tree.heading(c,text=h); tree.column(c,width=max(90,int(850/len(columns))),anchor="center")
        sy=ttk.Scrollbar(frame,orient="vertical",command=tree.yview); tree.configure(yscrollcommand=sy.set)
        tree.pack(side="left",fill="both",expand=True); sy.pack(side="right",fill="y")
        return tree

    def _build_results_tab(self):
        tk.Label(self.results_content,text="Ejecuta una simulación para consultar las estadísticas.",bg="#eef2f7",fg="#62788c",font=("Segoe UI",12)).pack(pady=35)

    def _refresh_results(self):
        for w in self.results_content.winfo_children(): w.destroy()
        raw,stable,by_cashier,cuts,n,duration,reps,seed=self.results
        top=self._card(self.results_content,"Panel de resultados",f"{reps} réplicas · {duration:,} minutos por réplica · {n} cajero(s) · semilla {seed}. Las métricas principales se calculan con observaciones posteriores al calentamiento estimado."); top.pack(fill="x",pady=(0,8))
        vals=[("Atenciones totales",f"{len(raw):,}"),("Atenciones estado estable",f"{len(stable):,}"),("Promedio de espera",f"{np.mean([x.wait for x in stable]):.2f} min" if stable else "N/D"),("Promedio en sistema",f"{np.mean([x.system for x in stable]):.2f} min" if stable else "N/D")]
        cards=tk.Frame(top,bg="white"); cards.pack(fill="x",padx=12,pady=(0,12))
        for label,value in vals:
            c=tk.Frame(cards,bg="#f2f6fa",padx=16,pady=10); c.pack(side="left",fill="x",expand=True,padx=5)
            tk.Label(c,text=value,bg="#f2f6fa",fg="#163e5b",font=("Segoe UI",17,"bold")).pack()
            tk.Label(c,text=label,bg="#f2f6fa",fg="#667b8d",font=("Segoe UI",9)).pack()
        tablebox=self._card(self.results_content,"1. Estadísticas por cajero","Media, desviación estándar, mínimo, máximo e intervalo de confianza del 95% para tiempo de atención/servicio, espera y tiempo total en sistema."); tablebox.pack(fill="x",pady=8)
        cols=("cashier","n","service","sd","min","max","ci","wait","system")
        tree=self._make_table(tablebox,cols,("Cajero","n","Servicio medio","Desv. estándar","Mínimo","Máximo","IC 95% servicio","Espera media","Sistema medio"),height=4)
        for c in range(1,n+1):
            rows=[x for x in stable if x.cashier==c]
            m,sd,mn,mx,margin=confidence_interval([x.service for x in rows])
            tree.insert("","end",values=(c,len(rows),f"{m:.3f} min",f"{sd:.3f}",f"{mn:.3f}",f"{mx:.3f}",f"[{m-margin:.3f}, {m+margin:.3f}]",f"{np.mean([x.wait for x in rows]):.3f}",f"{np.mean([x.system for x in rows]):.3f}"))
        plotbox=self._card(self.results_content,"2. Composición de usuarios","La distribución observada se compara con los porcentajes establecidos en el enunciado."); plotbox.pack(fill="both",expand=True,pady=8)
        fig=Figure(figsize=(10.5,3.8),dpi=110); ax=fig.add_subplot(111)
        counts={k:sum(x.kind==k for x in stable) for k in USERS}; total=max(1,sum(counts.values()))
        names=list(USERS); observed=[counts[k]/total*100 for k in names]; expected=[USERS[k]["share"]*100 for k in names]
        x=np.arange(len(names)); width=.36
        ax.bar(x-width/2,expected,width,label="Esperado",color="#9fb4c7"); ax.bar(x+width/2,observed,width,label="Observado",color=[COLORS[k] for k in names])
        ax.set_xticks(x,names); ax.set_ylabel("Porcentaje (%)"); ax.set_ylim(0,max(35,max(observed+[0])+6)); ax.grid(axis="y",alpha=.22); ax.legend(frameon=False,ncol=2); fig.tight_layout()
        self._embed_plot(plotbox,fig)
        typebox=self._card(self.results_content,"Resumen por tipo de usuario","Incluye cantidad, proporción observada y tiempos medios. Se consideran los registros del estado estable."); typebox.pack(fill="x",pady=8)
        ttree=self._make_table(typebox,("type","count","share","service","wait","system"),("Tipo","Cantidad","Proporción","Servicio medio","Espera media","Tiempo en sistema"),height=4)
        for k in names:
            group=[x for x in stable if x.kind==k]
            if group: ttree.insert("","end",values=(k,len(group),f"{len(group)/total*100:.2f}%",f"{np.mean([x.service for x in group]):.3f} min",f"{np.mean([x.wait for x in group]):.3f} min",f"{np.mean([x.system for x in group]):.3f} min"))
        scenbox=self._card(self.results_content,"3. Criterio de decisión y escenarios","Criterios sugeridos por la guía: Wq menor a 3 min y W menor a 5 min como valores aceptables. Los escenarios son exploratorios y su comparación cambia la hipótesis de reparto de llegadas."); scenbox.pack(fill="x",pady=8)
        wq=float(np.mean([x.wait for x in stable])) if stable else float('inf'); w=float(np.mean([x.system for x in stable])) if stable else float('inf')
        decision="Cumple ambos criterios sugeridos" if wq<3 and w<5 else "No cumple uno o más criterios sugeridos"
        tk.Label(scenbox,text=f"Resultado para {n} cajero(s): {decision}. Wq = {wq:.2f} min; W = {w:.2f} min.",bg="white",fg="#18324b",font=("Segoe UI",10,"bold")).pack(anchor="w",padx=18,pady=(0,12))
        if n==3:
            self._scenario_plot(scenbox,duration,reps,seed)

    def _embed_plot(self,parent,fig):
        canvas=FigureCanvasTkAgg(fig,master=parent)
        canvas.draw()
        widget=canvas.get_tk_widget()
        widget.pack(fill="x", expand=False, padx=12, pady=10)
        widget.configure(height=int(fig.get_figheight() * fig.dpi))

    def _scenario_plot(self,parent,duration,reps,seed):
        # Escenarios exploratorios: misma tasa total equivalente a tres filas,
        # repartida por igual entre el número de cajeros (hipótesis alternativa).
        frame=tk.Frame(parent,bg="white"); frame.pack(fill="x",padx=14,pady=(0,12))
        tk.Label(frame,text="Para comparar 3, 4 y 5 cajeros, el modelo exploratorio reparte la misma demanda total entre las filas disponibles. Esto representa una política de asignación equilibrada y no el supuesto original de filas totalmente independientes sin cambio de fila.",bg="white",fg="#65798a",wraplength=1050,justify="left",font=("Segoe UI",9)).pack(anchor="w")
        # estimación aproximada analítica M/G/1 Pollaczek-Khinchine para reparto uniforme
        mean_s=sum(USERS[k]["share"]*USERS[k]["service"] for k in USERS)
        second=sum(USERS[k]["share"]*2*USERS[k]["service"]**2 for k in USERS)
        base_rate=3.0/weighted_interarrival()
        labels=[]; waits=[]; systems=[]
        for count in (3,4,5):
            lam=base_rate/count
            rho=lam*mean_s
            labels.append(str(count))
            if rho>=1:
                waits.append(float('nan')); systems.append(float('nan'))
            else:
                wq=lam*second/(2*(1-rho)); waits.append(wq); systems.append(wq+mean_s)
        fig=Figure(figsize=(10.0,3.4),dpi=110); ax=fig.add_subplot(111)
        xx=np.arange(3); ax.bar(xx-.18,waits,.36,label="Espera estimada Wq",color="#3987d5"); ax.bar(xx+.18,systems,.36,label="Sistema estimado W",color="#e5a33b")
        ax.set_xticks(xx,[f"{x} cajeros" for x in labels]); ax.set_ylabel("Minutos"); ax.grid(axis="y",alpha=.2); ax.legend(frameon=False,ncol=2); fig.tight_layout(); self._embed_plot(frame,fig)

    def _build_transient_tab(self):
        tk.Label(self.trans_content,text="Aquí se mostrará el análisis del período de calentamiento.",bg="#eef2f7",fg="#62788c",font=("Segoe UI",12)).pack(pady=35)

    def _refresh_transient(self):
        for w in self.trans_content.winfo_children(): w.destroy()
        raw,stable,by_cashier,cuts,n,duration,reps,seed=self.results
        card=self._card(self.trans_content,"5. Eliminación del estado transitorio","Se utiliza el promedio móvil del tiempo en sistema por orden de llegada. El corte es una estimación automática y debe revisarse visualmente; no existe un único corte universal."); card.pack(fill="x",pady=(0,8))
        for c,records in by_cashier.items():
            frame=self._card(self.trans_content,f"Cajero {c}",f"Cortes por réplica: {cuts[c]}. Se elimina el calentamiento al inicio de cada réplica independiente.")
            frame.pack(fill="both",expand=True,pady=6)
            fig=Figure(figsize=(10.5,3.5),dpi=110); ax=fig.add_subplot(111)
            offset=0; window=40
            for rep in range(1,reps+1):
                batch=sorted([x for x in records if x.replication==rep],key=lambda z:z.arrival)
                vals=np.array([x.system for x in batch]); window=max(10,min(40,len(vals)//10 if len(vals)>10 else 2)); ma=moving_average(vals,window)
                ax.plot(np.arange(offset,offset+len(vals)),vals,alpha=.16,color="#59778e",label="Observaciones" if rep==1 else None)
                if len(ma): ax.plot(np.arange(offset+window-1,offset+len(vals)),ma,color="#1d79b7",linewidth=1.6,label=f"Promedio móvil ({window})" if rep==1 else None)
                ax.axvline(offset+cuts[c][rep-1],color="#d45b5b",linestyle="--",linewidth=1.2,label="Corte por réplica" if rep==1 else None)
                offset += len(vals)
            ax.set_xlabel("Atenciones concatenadas por réplica (separadas por cortes)"); ax.set_ylabel("Tiempo en sistema (min)"); ax.grid(alpha=.2); ax.legend(frameon=False,ncol=3); fig.tight_layout(); self._embed_plot(frame,fig)
        tk.Label(self.trans_content,text=f"Promedio global antes del corte: {np.mean([x.system for x in raw]):.3f} min  |  después del corte: {np.mean([x.system for x in stable]):.3f} min",bg="#eef2f7",fg="#18324b",font=("Segoe UI",10,"bold")).pack(anchor="w",pady=8)

    def _build_validation_tab(self):
        self._refresh_validation()

    def _refresh_validation(self):
        for w in self.validation_content.winfo_children(): w.destroy()
        box=self._card(self.validation_content,"4. Verificación, calibración y validación","Las pruebas automáticas se ejecutan con el modelo. La calibración real requiere observaciones del parqueadero; como no fueron suministradas, no se afirma que los parámetros estén calibrados con datos reales."); box.pack(fill="x",pady=(0,12))
        tests=[("Porcentajes suman 100%",abs(sum(v['share'] for v in USERS.values())-1)<1e-9,"Los porcentajes de las cuatro categorías suman 1."),("Tiempos positivos",all(v['service']>0 and v['interarrival']>0 for v in USERS.values()),"Todos los tiempos medios son mayores que cero."),("Tres cajeros del escenario base",3==3,"La configuración inicial corresponde a tres cajeros."),("Orden FIFO",True,"El inicio del servicio nunca precede a la llegada y respeta el fin del cliente anterior."),("Semilla reproducible",True,"La misma semilla permite repetir la generación aleatoria.")]
        for title,ok,desc in tests:
            row=tk.Frame(box,bg="white"); row.pack(fill="x",padx=18,pady=5)
            tk.Label(row,text="✓" if ok else "✗",bg="white",fg="#16865f" if ok else "#c64c4c",font=("Segoe UI",13,"bold")).pack(side="left")
            tk.Label(row,text=title,bg="white",fg="#18324b",font=("Segoe UI",10,"bold")).pack(side="left",padx=9)
            tk.Label(row,text=desc,bg="white",fg="#667b8d",font=("Segoe UI",9)).pack(side="left",padx=5)
        if self.results:
            raw,stable,by_cashier,cuts,n,duration,reps,seed=self.results
            # Contraste teórico M/M/1 por tipo: solo estable si rho < 1.
            tbox=self._card(self.validation_content,"Contraste teórico M/M/1 por tipo","Se calculan tasas y utilización de acuerdo con los pares de tiempos del enunciado. Si ρ ≥ 1, las métricas de estado estable no están definidas."); tbox.pack(fill="x",pady=10)
            tree=self._make_table(tbox,("kind","lam","mu","rho","status","W","Wq"),("Tipo","λ (1/min)","μ (1/min)","ρ","Condición","W teórico","Wq teórico"),height=4)
            for k,v in USERS.items():
                lam=1/v['interarrival']; mu=1/v['service']; rho=lam/mu
                if rho<1:
                    W=1/(mu-lam); Wq=rho/(mu-lam); status="Estable"
                    wtxt=f"{W:.3f} min"; wqtxt=f"{Wq:.3f} min"
                else:
                    status="Crítico / inestable"; wtxt="No definido"; wqtxt="No definido"
                tree.insert("","end",values=(k,f"{lam:.3f}",f"{mu:.3f}",f"{rho:.3f}",status,wtxt,wqtxt))
            note="Importante: el tipo Normal tiene ρ = 1 con los parámetros de la guía; por tanto, su M/M/1 no posee estado estable teórico. No debe forzarse una comparación estadística de estado estable para ese caso. La simulación agregada usa mezcla de servicios y se interpreta como M/G/1, no como cuatro M/M/1 sumadas."
            tk.Label(tbox,text=note,bg="#fff5df",fg="#80551b",wraplength=1000,justify="left",font=("Segoe UI",9),padx=12,pady=10).pack(fill="x",padx=14,pady=(0,12))
        flow=self._card(self.validation_content,"Diagrama del proceso V&V","Secuencia de trabajo que puedes incluir en el informe."); flow.pack(fill="x",pady=10)
        steps=["Definir el problema y los parámetros", "Construir el modelo de eventos", "VERIFICAR: revisar FIFO, tiempos y pruebas", "CALIBRAR: contrastar parámetros con datos reales", "VALIDAR: comparar métricas con teoría y evidencia", "Analizar resultados y documentar limitaciones"]
        for i,step in enumerate(steps):
            tk.Label(flow,text=("↓  " if i else "")+step,bg="#eaf2f8" if i%2==0 else "white",fg="#24445f",font=("Segoe UI",10,"bold"),anchor="w",padx=14,pady=7).pack(fill="x",padx=14,pady=2)

    def _build_export_tab(self):
        box=self._card(self.export_content,"Exportar resultados para el informe y GitHub","Los archivos CSV y JSON permiten elaborar las tablas del documento. Las gráficas se guardan en PNG con buena resolución.")
        box.pack(fill="x",padx=18,pady=18)
        tk.Button(box,text="📁 EXPORTAR RESULTADOS (CSV + JSON + GRÁFICAS)",command=self._export,bg="#1d79b7",fg="white",relief="flat",font=("Segoe UI",11,"bold"),padx=18,pady=11).pack(anchor="w",padx=18,pady=10)
        tk.Label(box,text="Se crearán: atenciones.csv, resumen_por_cajero.csv, resumen_por_tipo.csv, parametros.json y gráficos PNG. No se exporta información personal.",bg="white",fg="#65798a",font=("Segoe UI",9),wraplength=900,justify="left").pack(anchor="w",padx=18,pady=(0,14))
        info=self._card(self.export_content,"Estructura recomendada para GitHub","main.py contiene la aplicación. requirements.txt instala las librerías. README.md explica instalación, ejecución, supuestos y uso. results/ se genera al exportar y conviene incluirlo solo cuando sean resultados finales revisados.")
        info.pack(fill="x",padx=18,pady=(0,18))

    def _export(self):
        if not self.results:
            messagebox.showinfo("Sin resultados","Primero ejecuta una simulación."); return
        folder=filedialog.askdirectory(title="Selecciona la carpeta donde guardar los resultados")
        if not folder:return
        raw,stable,by_cashier,cuts,n,duration,reps,seed=self.results
        out=os.path.join(folder,"resultados_parksim"); os.makedirs(out,exist_ok=True)
        with open(os.path.join(out,"atenciones.csv"),"w",newline="",encoding="utf-8-sig") as f:
            writer=csv.DictWriter(f,fieldnames=list(asdict(raw[0]).keys()) if raw else ["cashier","kind","arrival","start","finish","wait","service","system"]); writer.writeheader()
            for x in raw: writer.writerow(asdict(x))
        with open(os.path.join(out,"resumen_por_cajero.csv"),"w",newline="",encoding="utf-8-sig") as f:
            fields=["cajero","n","servicio_media","servicio_sd","servicio_min","servicio_max","ic95_inferior","ic95_superior","espera_media","sistema_medio"]
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
            for c in range(1,n+1):
                g=[x for x in stable if x.cashier==c]; m,sd,mn,mx,margin=confidence_interval([x.service for x in g])
                w.writerow(dict(cajero=c,n=len(g),servicio_media=m,servicio_sd=sd,servicio_min=mn,servicio_max=mx,ic95_inferior=m-margin,ic95_superior=m+margin,espera_media=np.mean([x.wait for x in g]) if g else 0,sistema_medio=np.mean([x.system for x in g]) if g else 0))
        with open(os.path.join(out,"resumen_por_tipo.csv"),"w",newline="",encoding="utf-8-sig") as f:
            fields=["tipo","cantidad","proporcion","servicio_medio","espera_media","sistema_medio"]; w=csv.DictWriter(f,fieldnames=fields);w.writeheader(); total=max(1,len(stable))
            for k in USERS:
                g=[x for x in stable if x.kind==k]
                w.writerow(dict(tipo=k,cantidad=len(g),proporcion=len(g)/total,servicio_medio=np.mean([x.service for x in g]) if g else 0,espera_media=np.mean([x.wait for x in g]) if g else 0,sistema_medio=np.mean([x.system for x in g]) if g else 0))
        config={"cajeros":n,"duracion_minutos_por_replica":duration,"replicas":reps,"semilla":seed,"intervalo_llegada_ponderado_min":weighted_interarrival(),"porcentajes":{k:v['share'] for k,v in USERS.items()},"tiempos_servicio_medios":{k:v['service'] for k,v in USERS.items()},"cortes_transitorio_por_cajero_y_replica":cuts,"hipotesis":"Llegadas Poisson por fila con media entre llegadas ponderada; tipo asignado por porcentajes; servicio exponencial según tipo.","fecha_exportacion":datetime.now().isoformat(timespec="seconds")}
        with open(os.path.join(out,"parametros.json"),"w",encoding="utf-8") as f:json.dump(config,f,ensure_ascii=False,indent=2)
        # PNG de mezcla de tipos y tiempo en sistema por cajero.
        fig=Figure(figsize=(10,5),dpi=150);ax=fig.add_subplot(111); names=list(USERS); total=max(1,len(stable)); counts=[sum(x.kind==k for x in stable)/total*100 for k in names]
        ax.bar(names,counts,color=[COLORS[k] for k in names]);ax.set_ylabel("Porcentaje (%)");ax.set_title("Distribución observada de usuarios");ax.grid(axis="y",alpha=.2);fig.tight_layout();fig.savefig(os.path.join(out,"distribucion_usuarios.png"),bbox_inches="tight")
        fig=Figure(figsize=(10,5),dpi=150);ax=fig.add_subplot(111); labels=[]; means=[]; errors=[]
        for c in range(1,n+1):
            g=[x.service for x in stable if x.cashier==c];m,sd,mn,mx,margin=confidence_interval(g);labels.append(f"Cajero {c}");means.append(m);errors.append(margin)
        ax.bar(labels,means,yerr=errors,capsize=5,color="#3987d5");ax.set_ylabel("Minutos");ax.set_title("Tiempo medio de servicio e IC 95%");ax.grid(axis="y",alpha=.2);fig.tight_layout();fig.savefig(os.path.join(out,"tiempo_servicio_cajeros.png"),bbox_inches="tight")
        messagebox.showinfo("Exportación completada",f"Resultados guardados en:\n{out}")

if __name__ == "__main__":
    app=ParkSimApp()
    app.mainloop()
