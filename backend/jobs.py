"""
Fila simples de jobs em background (uma thread).

Um job por vez: a GPU de 4 GB não aguenta dois Whispers/renders em paralelo.
Cada projeto tem um Event de cancelamento, verificado dentro do pipeline.
"""
import logging
import queue
import threading
import time
import traceback

import projetos
from config import Cancelado

log = logging.getLogger("jobs")


class FilaJobs:
    def __init__(self):
        self._fila: queue.Queue = queue.Queue()
        self._cancelar: dict[str, threading.Event] = {}
        self._thread = None
        self.atual: dict | None = None
        # Ganchos opcionais por projeto: antes(pid, cancelado, tipo) roda antes de cada job (ex.: baixar de novo o
        # vídeo de um link) e depois(pid, pendentes) depois (ex.: apagar o vídeo quando não sobra trabalho)
        self.antes = None
        self.depois = None

    def iniciar(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, daemon=True, name="jobs")
            self._thread.start()

    def evento(self, pid: str) -> threading.Event:
        return self._cancelar.setdefault(pid, threading.Event())

    def enviar(self, pid: str, tipo: str, funcao, cid: str | None = None):
        """funcao(cancelado: Event) é executada na thread."""
        self.evento(pid).clear()
        self._fila.put({"pid": pid, "tipo": tipo, "funcao": funcao, "cid": cid, "enviado": time.time()})
        log.info("Job na fila: %s %s %s", tipo, pid, cid or "")

    def cancelar(self, pid: str):
        self.evento(pid).set()

    def pendentes(self) -> int:
        return self._fila.qsize()

    def pendentes_do(self, pid: str) -> int:
        with self._fila.mutex:
            return sum(1 for j in self._fila.queue if j["pid"] == pid)

    def _loop(self):
        while True:
            job = self._fila.get()
            pid, cid, tipo = job["pid"], job["cid"], job["tipo"]
            evento = self.evento(pid)
            if evento.is_set():
                self._marcar_cancelado(pid, cid, tipo)
                continue
            self.atual = job
            log.info("Iniciando job %s %s %s", tipo, pid, cid or "")
            try:
                if self.antes:
                    self.antes(pid, evento, tipo)
                job["funcao"](evento)
                log.info("Job concluído: %s %s", tipo, pid)
            except Cancelado:
                log.info("Job cancelado: %s %s", tipo, pid)
                self._marcar_cancelado(pid, cid, tipo)
            except Exception as e:
                log.error("Job falhou: %s %s\n%s", tipo, pid, traceback.format_exc())
                self._marcar_erro(pid, cid, tipo, str(e))
            finally:
                self.atual = None
                evento.clear()
                if self.depois:
                    try:
                        self.depois(pid, self.pendentes_do(pid))
                    except Exception as e:  # limpeza nunca derruba a fila
                        log.warning("Pós-job falhou para %s: %s", pid, e)

    @staticmethod
    def _marcar_cancelado(pid, cid, tipo):
        def f(m):
            if tipo == "processar":
                m["status"] = "cancelado"
            _destravar_clips(m)
        try:
            projetos.atualizar(pid, f)
        except KeyError:
            pass

    @staticmethod
    def _marcar_erro(pid, cid, tipo, mensagem):
        def f(m):
            if tipo == "processar":
                m.update(status="erro", erro=mensagem)
            else:
                if cid:
                    projetos.clip(m, cid)["erro"] = mensagem
                m["avisos"].append(f"Falha em '{tipo}': {mensagem}")
                _destravar_clips(m)
        try:
            projetos.atualizar(pid, f)
        except KeyError:
            pass


def _destravar_clips(meta: dict):
    """Clipes que ficaram 'na fila'/'renderizando' voltam ao estado anterior."""
    for c in meta.get("clips", []):
        if c.get("status") in ("fila", "renderizando", "cortado"):
            c["status"] = "pronto" if c.get("arquivo") else "erro"


fila = FilaJobs()
