from LnkSupport import LnkModule as LM
from NetSupport import NetModule as NM
from AppSupport import AppModule as AM
from CmdSupport import CmdModule as CM

import os
import re
import logging

HOST='127.0.0.1'


def port(Dev,Lev,Entity):
    '''
    输入设备号层次和实体号 最后输出一个本项目规则的端口号 全是int形
    '''
    if type(Lev)==type('string'):
        if Lev=='PHY':
            Lev=1
        elif Lev=='LNK':
            Lev=2
        elif Lev=='NET':
            Lev=3
        elif Lev=='APP':
            Lev=4
        else:
            Lev=9
    return 10000+Dev*1000+Lev*100+Entity

#准备主函数日志
logger_main = logging.getLogger(__name__)
logger_main.setLevel(level = logging.DEBUG)

formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
if os.path.isfile("log_warning.txt"):
    os.remove("log_warning.txt")
handler_warning_main = logging.FileHandler("log_warning.txt")
handler_warning_main.setLevel(logging.WARNING)
handler_warning_main.setFormatter(formatter)
logger_main.addHandler(handler_warning_main)

if os.path.isfile("log_debug_main.txt"):
    os.remove("log_debug_main.txt")
handler_debug_main = logging.FileHandler("log_debug_main.txt")
handler_debug_main.setLevel(logging.DEBUG)
handler_debug_main.setFormatter(formatter)
logger_main.addHandler(handler_debug_main)

console_handler = logging.StreamHandler()
console_handler.setLevel(logging.ERROR)
logger_main.addHandler(console_handler)

cmd={'ip':'127.0.0.1','port':20000} #默认地址设定
with open('ne.txt',mode='r') as ne:
    tx=''
    flag=0
    while True:
        tx = ne.readline()  # 读取一行保存在tx里面
        if tx == '' or flag == 2:  # 只有文件末尾才会有这种情况
            break

        tx = re.split('#', tx)[0]  # 去除行末注释
        tx=re.sub('\s', '', tx)
        numdev=re.match('\d+',tx)
        if tx == '':  # 空行或者开头#都会直接忽略掉  这里的#是比较灵活的
            continue
        elif re.search('cmdIpAddr=', tx):
            cmd['ip'] = tx[re.search('cmdIpAddr=', tx).end():]  # 最后有个换行符 要屏蔽掉
            flag+=1
            continue
        elif re.search('cmdPort=', tx):
            cmd['port'] = int(tx[re.search('cmdPort=', tx).end():])
            flag+=1
            continue
cmd_addr = (cmd['ip'], cmd['port'])#控制平台地址

#开启控制平台日志
if os.path.isfile("log_debug_CMD.txt"):
    os.remove("log_debug_CMD.txt")
handler_CMD=logging.FileHandler("log_debug_CMD.txt")
handler_CMD.setLevel(logging.DEBUG)
handler_CMD.setFormatter(formatter)
logger_CMD=logging.getLogger("CMD")
logger_CMD.setLevel(level = logging.DEBUG)
logger_CMD.addHandler(handler_CMD)

#初始化控制平台窗口
CMD=CM(cmd_addr, [], logger=logger_CMD,daemon=True)
screenwidth=CMD.root.winfo_screenwidth()
screenheight=CMD.root.winfo_screenheight()

#读取ne文件开启窗口
with open('ne.txt',mode='r') as ne:
    tx = '#something'
    tmpupper = {'PHY': None, 'LNK': None, 'NET': None, 'APP': None} #记录最近的上层实体
    handler_debug={}                                                #日志处理器debug日志字典
    logger_debug={}                                                 #日志获取器debug日志字典
    nowdev=-1                                                       #当前设备号
    nowlayer=''                                                     #当前设备层次
    while True:
        tx = ne.readline()  #读取一行保存在tx里面
        if tx=='':          #Python只有文件末尾才会有这种情况
            break

        tx = re.split('#', tx)[0]   #去除行末注释
        if re.sub('\s','',tx)=='':  #空行或者开头#都会直接忽略掉  这里的#是比较灵活的
            continue
        elif not re.search('--',tx) and not re.search('=',tx):  #只看topo部分 靠这两个过滤掉其他部分
            tmp_ett=[i for i in re.split('\s+',tx) if i != '']  #根据间隔切分本行的每个实体（或者开头数字）
            for txi in tmp_ett:
                if re.match('\d',txi)!=None:#设备号更新了
                    nowdev=int(txi)
                    logger_debug[nowdev] = logging.getLogger('{}.Dev[{}]'.format(__name__,nowdev))
                    logger_debug[nowdev] .setLevel(level=logging.DEBUG)

                    if os.path.isfile("log_debug_Dev[{}].txt".format(nowdev)):
                         os.remove("log_debug_Dev[{}].txt".format(nowdev))
                    handler_debug[nowdev] = logging.FileHandler("log_debug_Dev[{}].txt".format(nowdev))
                    handler_debug[nowdev].setLevel(logging.DEBUG)
                    handler_debug[nowdev].setFormatter(formatter)

                    logger_debug[nowdev].addHandler(handler_debug[nowdev])
                    logger_debug[nowdev].info('设备{}记录器启动完成'.format(nowdev,logger_debug))

                    CMD.newdev(nowdev)
                    continue
                else:
                    layer=re.search('[a-zA-Z]+',txi).group()
                    no=int( re.search('[0-9]+',txi).group() )
                    ports=port(nowdev, layer, no)
                    #这里开始开小窗了：
                    if layer=='PHY':
                        CMD.add_sendlist([(HOST, ports)])
                        os.system("start 物理层模拟软件.exe {} {}".format(nowdev,no))
                        CMD.newphy(nowdev,no)

                    elif layer=='LNK':
                        CMD.add_sendlist([(HOST, ports)])
                        tmpD = LM(nowdev, no, Host=HOST, x=((nowdev - 1) * 310) % (screenwidth), y=500, cmd_addr=cmd_addr, logger=logger_debug[nowdev])
                        tmpD.start()
                        CMD.newlnk(nowdev,ports,no)

                    elif layer=='NET':
                        CMD.add_sendlist([(HOST, ports)])
                        tmpD = NM(nowdev, no, Host=HOST, x=((nowdev - 1) * 310) % (screenwidth), y=300, cmd_addr=cmd_addr, logger=logger_debug[nowdev])
                        tmpD.start()
                        CMD.newnet(nowdev,ports,no)

                    elif layer=='APP':
                        CMD.add_sendlist([(HOST, ports)])
                        tmpD = AM(nowdev, no, Host=HOST, x=((nowdev - 1) * 310) % (screenwidth), y=0, cmd_addr=cmd_addr, logger=logger_debug[nowdev])
                        tmpD.start()
                        CMD.newapp(nowdev,ports,no)

                    else:
                        logger_main.warning('分析ne文件layer匹配失败')

logger_main.info('窗口开启完毕')

CMD.start()
CMD.root.mainloop()#进入CMD主循环
logger_main.critical('主程序退出\n----------------------------------------------------------------------')



