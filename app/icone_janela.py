"""
Ícone nítido na barra de tarefas para a janela do Gadosso Edit.

O Edge/Chrome em modo aplicativo usa o favicon da página (16 px) como ícone da janela e o Windows estica esse
ícone para a barra de tarefas: fica borrado. Aqui o lançador acha a janela do app e:
  1. troca o ícone dela pelo do app/icone.ico, carregado no tamanho exato que o Windows pede (conforme o zoom
     da tela), em vez do favicon esticado;
  2. dá a ela uma identidade própria no Windows (AppUserModelID), separada do Edge comum, com o comando e o
     ícone de reabrir: fixar na barra de tarefas cria um atalho que abre o Gadosso Edit com o ícone certo.
O navegador às vezes põe o favicon de volta (ao recarregar a página), então a troca é conferida a cada 2 s.
Só usa ctypes (nada a instalar).
"""
import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

TITULO = "Gadosso Edit"
APP_ID = "GadossoEdit.App"
ICONE = Path(__file__).with_name("icone.ico")
LANCADOR = Path(__file__).with_name("clipador.pyw")

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")
ole32 = ctypes.WinDLL("ole32")

WM_SETICON, WM_GETICON = 0x0080, 0x007F
ICON_SMALL, ICON_BIG = 0, 1
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXICON, SM_CXSMICON = 11, 49
VT_LPWSTR = 31

user32.LoadImageW.restype = wintypes.HANDLE
user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.SendMessageW.restype = ctypes.c_ssize_t
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]
user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __init__(self, texto: str):
        super().__init__()
        ole32.CLSIDFromString(ctypes.c_wchar_p(texto), ctypes.byref(self))


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]


class PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.USHORT), ("r2", wintypes.USHORT), ("r3", wintypes.USHORT),
                ("valor", ctypes.c_wchar_p), ("extra", ctypes.c_void_p)]


IID_IPROPERTYSTORE = GUID("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
_FMT_APPID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"
PKEY_ID, PKEY_RELANCAR_CMD, PKEY_RELANCAR_ICONE, PKEY_RELANCAR_NOME = 5, 2, 3, 4
_E_PROTOTIPO = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT))
_COMMIT = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p)
_RELEASE = ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)


def _identidade(hwnd: int) -> None:
    """Grava o AppUserModelID e os dados de "reabrir" na janela (IPropertyStore da janela)."""
    loja = ctypes.c_void_p()
    if shell32.SHGetPropertyStoreForWindow(wintypes.HWND(hwnd), ctypes.byref(IID_IPROPERTYSTORE), ctypes.byref(loja)) != 0:
        return
    vtabela = ctypes.cast(ctypes.cast(loja, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
    set_value, commit, release = _E_PROTOTIPO(vtabela[6]), _COMMIT(vtabela[7]), _RELEASE(vtabela[2])
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    valores = {
        PKEY_RELANCAR_CMD: f'"{pythonw}" "{LANCADOR}"',
        PKEY_RELANCAR_ICONE: f"{ICONE},0",
        PKEY_RELANCAR_NOME: TITULO,
        PKEY_ID: APP_ID,  # o ID por último: é ele que faz o Windows reler os outros
    }
    try:
        for pid, texto in valores.items():
            chave = PROPERTYKEY(GUID(_FMT_APPID), pid)
            valor = PROPVARIANT(vt=VT_LPWSTR, valor=texto)
            set_value(loja, ctypes.byref(chave), ctypes.byref(valor))
        commit(loja)
    finally:
        release(loja)


def _janelas_do_app() -> list[int]:
    achadas = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            classe, titulo = ctypes.create_unicode_buffer(64), ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, classe, 64)
            user32.GetWindowTextW(hwnd, titulo, 256)
            if classe.value == "Chrome_WidgetWin_1" and titulo.value == TITULO:
                achadas.append(hwnd)
        return True

    user32.EnumWindows(cada, 0)
    return achadas


_cache_icones: dict[int, int] = {}


def _icone(lado: int) -> int:
    if lado not in _cache_icones:
        _cache_icones[lado] = user32.LoadImageW(None, str(ICONE), IMAGE_ICON, lado, lado, LR_LOADFROMFILE) or 0
    return _cache_icones[lado]


def ajustar(hwnd: int, ja_feitas: set[int]) -> None:
    dpi = user32.GetDpiForWindow(hwnd) or 96
    grande = _icone(user32.GetSystemMetricsForDpi(SM_CXICON, dpi))
    pequeno = _icone(user32.GetSystemMetricsForDpi(SM_CXSMICON, dpi))
    if grande and user32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0) != grande:
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, grande)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, pequeno)
    if hwnd not in ja_feitas:
        _identidade(hwnd)
        ja_feitas.add(hwnd)


def vigiar() -> None:
    """Roda para sempre numa thread do lançador (custo desprezível: uma varredura de janelas a cada 2 s)."""
    if sys.platform != "win32" or not ICONE.exists():
        return
    ole32.CoInitialize(None)
    ja_feitas: set[int] = set()
    while True:
        try:
            for hwnd in _janelas_do_app():
                ajustar(hwnd, ja_feitas)
        except Exception:
            pass
        time.sleep(2)


if __name__ == "__main__":  # teste manual: ajusta a janela aberta agora e sai
    ole32.CoInitialize(None)
    janelas = _janelas_do_app()
    for h in janelas:
        ajustar(h, set())
    print(f"{len(janelas)} janela(s) ajustada(s)")
