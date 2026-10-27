import pyautogui
import time


def executar_automacao():
    try:
                
        # clicar no navegador do InContrl
        pyautogui.click(377,20,duration=3)

        # clicar no id da pagina de logs
        pyautogui.doubleClick(1279,192,duration=3)
        #esperar um tempo
        time.sleep(1)
        # copiar id da pagina de logs
        pyautogui.hotkey('ctrl', 'c')
        # clicar no navegador do sistema de pesagem
        pyautogui.click(158,26,duration=2)
        # clicar em user id
        pyautogui.click(547,216,duration=2)
        # colar user id
        pyautogui.hotkey('ctrl', 'v')
        # clicar em buscar
        pyautogui.click(532,262, duration=2)
        #aguardar 1 segundo
        time.sleep(1)
        #abrir funcionalidade de impressao
        pyautogui.hotkey('ctrl', 'p')
        #clicar em numero de impressoes
        pyautogui.doubleClick(1033,280, duration=1)
        #aguardar um segundo
        time.sleep(1)
        #inserir quantidade de copias
        pyautogui.typewrite('3')
        #clicar em imprimir 
        pyautogui.click(1056,700, duration=1)
        #esperar
        time.sleep(2)
        #clicar na barra de rolagem
        pyautogui.click(1431,289,duration=1)
        time.sleep(1)
        #arrastar para baixo
        pyautogui.drag(0,300,duration=1)
        # registar peso
        pyautogui.click(555,710,duration=2)


    except Exception as e:
        print(f"ërro ao executar automacao: {str(e)}")