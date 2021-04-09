import threading
import socket
import tkinter as tk

import time
import re
import os
import logging

'''
调色板：
灰色：#DDDDDD None n
浅绿：#33FF33 接受 r
红色：#FF0033 发送 s

'''
class CmdModule(threading.Thread):
    def __init__(self,localaddr,sendlist,logger,clscmd=b'exit\0',daemon=False):
        super().__init__(daemon=daemon)
        self.buffer=[]
        self.sendlist=sendlist      #可以一次传入，也可以逐次添加
        self.local_addr=localaddr
        self.clscmd=clscmd          #关闭指令可自定义
        self.logger=logger

        self.root = self.newroot()  #初始化窗口组件
        self.working=True           #手动循环的判断条件

#-------------------------------发送函数-------------------------------
    def cmdsend(self,data:bytes,port):
        addr=('127.0.0.1',port)
        for i in self.sendlist:
            if i[1]==port:
                addr=i
                break

        self.socket.sendto(data,addr)
#-------------------------------接收函数-------------------------------
    def main_recv(self,data,addr):#主要职责是更改按钮颜色hhh
        get=data.decode()

        port=addr[1]
        Dev=int(str(port)[1])
        Lev=int(str(port)[2])
        Layer=''
        if Lev==1:
            Layer='PHY'
        elif Lev==2:
            Layer='LNK'
        elif Lev==3:
            Layer='NET'
        elif Lev==4:
            Layer='APP'
        Entity=int(str(port)[3:])
        if Layer!='':
            self.dev[Dev][Layer][Entity]['btn'].configure(bg=get)


        return True

    #控制层这里的设计使得压力大的时候能够快速消化buffer包，在平时压力小的时候可以较为缓慢的观看各实体工作状态
    #相应的这里的f默认值其实没有很有用
    def rcv_FromSocket_loop(self, f=0.01):
        '''
        开始尝试接受内容，接收到的消息会原封不动的保存self.buff中，用其他函数来提取。
        同时也会停止接收内容直到重新启动该函数（可以在函数外人为控制每次接收到都直接启动,直接启动可能会比较ok
        :param f: 检查接口的频率 单位是秒
        :return:None
        '''
        self.rsvtimer = threading.Timer(f, self.rcv_FromSocket_loop, ( 0.0160 if len(self.buffer) > 100 else 0.01,))
        self.rsvtimer.start()
        try:
            tmp=self.socket.recvfrom(65536)
            assert len(tmp)!=0
        except:
            return
        self.buffer.append(tmp)
        self.Lab_buffer.configure(text="buffer:{}".format(len(self.buffer)))
        return

    def rcv_FromBuff_loop(self, f=0.05):
        timer = threading.Timer(f, self.rcv_FromBuff_loop, (0.02 if len(self.buffer) > 50 else 0.1,))
        if len(self.buffer)!=0:
            rtn = self.buffer.pop(0)#以略微增加处理帧的时间为代价 确保不会出现提取失败的情况 （提取速度频率有个基础时间了 可以写0了）
            timer.start()
            self.Lab_buffer.configure(text="buffer:{}".format(len(self.buffer)))
            try:
                self.logger.debug('*-*-*-*-*-*-*控制层收到了一个帧*-*-*-*-*-*-*'.format())
                self.main_recv(*rtn)
                self.logger.debug('*-*-*-*-*-*-*控制层处理了一个帧*-*-*-*-*-*-*\n'.format())
            except Exception as z :
                self.logger.warning("控制层接受出错，原因：{}".format(z))
        else:
            timer.start()
        return

#===============================控制函数-------------------------------
    def add_sendlist(self,lists):
        for i in lists:
            self.sendlist.append(i)

    def close_win_all(self):
        for i in self.sendlist:
            self.socket.sendto(self.clscmd, i)
        self.btnc4.configure(text='清理log', command=self.close_win_all_2)
        return
    def close_win_all_2(self):
        for i in os.listdir(os.getcwd()):
            if re.match('datarecd', i) != None:
                os.remove(i)
        self.new_destroy()

    def DVstart(self):
        for i in self.sendlist:
            if i[1]%1000-i[1]%100==300:#向网络层发送这个指令 可能链路层要被发送
                self.socket.sendto(b'DVstart\0',i)
        #每个多长时间执行一次DV算法 默认25s一次
    def autoDVloop(self,t=25):
        self.DVstart()
        timer=threading.Timer(t,self.autoDVloop,(t,))
        timer.start()
        return

    def show_all_win(self):
        for i in self.sendlist:
            self.socket.sendto(b'show\0',i)
        self.btnc2.configure(command=self.hide_all_win, text='隐藏所有')
    def hide_all_win(self):
        for i in self.sendlist:
            self.socket.sendto(b'hide\0',i)
        self.btnc2.configure(command=self.show_all_win, text='显示所有')

    def clear_buffer(self):
        self.buffer=[]
        self.Lab_buffer.configure(text="buffer:0".format(len(self.buffer)))
        for dev in self.dev:
            for layer in self.dev[dev]:
                for entity in self.dev[dev][layer]:
                    self.dev[dev][layer][entity]['btn'].configure(bg='#DDDDDD')
#--------------------------------可视化控制-----------------------------
    def new_destroy(self):
        #关闭窗口并退出循环
        self.working=False
        self.root.destroy()

    def newroot(self):
        self.dev = {}
        self.devfrm = {}
        self.root = tk.Tk()

        self.root.title('控制平台')
        self.root.geometry('500x500')

        frmcommand = tk.Frame(self.root, relief=tk.GROOVE, bg='#000033')
        frmcommand.place(relx=1, rely=0, relheight=1, x=-100, width=100)

        btnc1 = tk.Button(frmcommand, text='退出', command=self.new_destroy)
        btnc1.place(relx=0.05, rely=1, height=30, relwidth=0.9, y=-32 - 6)

        self.Lab_buffer = tk.Label(frmcommand, text='buffer:{}'.format(len(self.buffer)), relief=tk.GROOVE)
        self.Lab_buffer.place(relx=0.05, rely=1, height=30, relwidth=0.9, y=-64 - 6)

        self.btnc2 = tk.Button(frmcommand, text='显示所有', command=self.show_all_win)
        self.btnc2.place(relx=0.05, rely=0, height=30, relwidth=0.9, y=0 + 6)

        btnc3 = tk.Button(frmcommand, text='动态路由', command=self.DVstart)
        btnc3.place(relx=0.05, rely=0, height=30, relwidth=0.9, y=32 + 6)

        self.btnc4 = tk.Button(frmcommand, text='一键关闭', command=self.close_win_all)
        self.btnc4.place(relx=0.05, rely=0, height=30, relwidth=0.9, y=64 + 6)

        btnc5 = tk.Button(frmcommand, text='清空缓存', command=self.clear_buffer)
        btnc5.place(relx=0.05, rely=0, height=30, relwidth=0.9, y=96 + 6)

        self.frmdev = tk.Frame(self.root, relief=tk.GROOVE, bg='#3366CC')
        self.frmdev.place(relx=0, rely=0, relheight=1, relwidth=1, width=-100)
        return self.root

    def newdev(self, dev):#开辟一个新的设备
        if dev in self.dev.keys():
            return
        self.dev[dev]={'APP':{},'NET':{},'LNK':{},'PHY':{}}
        x = 10 + (len(self.dev) - 1) % 3 * 130
        y = 10 + int((len(self.dev) - 1) / 3) * 130

        self.devfrm[dev] = tk.Frame(self.frmdev, bg='#00FF00')
        self.devfrm[dev].place(x=x, y=y, height=120, width=120)
        laber = tk.Label(self.devfrm[dev], text='设备{}'.format(dev), fg='black', font=("黑体", 9), anchor=tk.CENTER, relief=tk.RAISED)
        laber.place(relx=0, rely=0, height=20, relwidth=1)

    def newapp(self, dev, port, entity=0):
        btn   = tk.Button(self.devfrm[dev],text='APP{}'.format(entity),command=None,relief=tk.GROOVE,bg='#DDDDDD')
        self.dev[dev]['APP']={entity:{"port":port, 'btn':btn}}
        btn.configure(command=lambda :self.win_show(port=self.dev[dev]['APP'][entity]['port'], btn=btn))
        btn.place(x=0, y=20, height=25, relwidth=1)
    def newnet(self, dev, port, entity=0):
        btn = tk.Button(self.devfrm[dev], text='NET{}'.format(entity), command=None,relief=tk.GROOVE,bg='#DDDDDD')
        self.dev[dev]['NET'] = {entity: {"port":port, 'btn':btn}}
        btn.configure(command=lambda :self.win_show(port=self.dev[dev]['NET'][entity]['port'], btn=btn))
        btn.place(x=0, y=45, height=25, relwidth=1)
    def newlnk(self, dev, port, entity):
        btn = tk.Button(self.devfrm[dev], text='LNK{}'.format(entity), command=None,relief=tk.GROOVE,bg='#DDDDDD')
        self.dev[dev]['LNK'][entity] = {"port": port, 'btn': btn}
        btn.configure(command=lambda :self.win_show(port=self.dev[dev]['LNK'][entity]['port'], btn=btn))

        entity_num=len(self.dev[dev]['LNK'])
        width=120/entity_num
        count=-1
        for i in self.dev[dev]['LNK']:
            count+=1
            self.dev[dev]['LNK'][i]['btn'].place(y=70,height=25,width=width,x=count*width)
    def newphy(self, dev, entity):
        btn = tk.Button(self.devfrm[dev], text='PHY{}'.format(entity), command=None,relief=tk.GROOVE,bg='#DDDDDD')
        self.dev[dev]['PHY'][entity] = {"port": None, 'btn': btn}

        entity_num = len(self.dev[dev]['PHY'])
        width = 120 / entity_num
        count = -1
        for i in self.dev[dev]['PHY']:
            count += 1
            self.dev[dev]['PHY'][i]['btn'].place(y=95, height=25, width=width, x=count * width)

    def win_show(self, port, btn):
        if port==None:
            print('这个按钮不能工作')
        else:
            self.cmdsend(b'show\0', port)
            btn.configure(command=lambda :self.win_hide(port, btn))
    def win_hide(self, port, btn):
        if port==None:
            print('这个按钮不能工作')
        else:
            self.cmdsend(b'hide\0',port)
            btn.configure(command=lambda :self.win_show(port, btn))

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(self.local_addr)
            s.setblocking(False)
            self.socket=s
            self.rcv_FromSocket_loop(0.01)#主控传入数据大小不是很重要
            self.rcv_FromBuff_loop(0.05)
            self.autoDVloop()              #开局先进行一次动态路由
            while self.working:#我也想在这里面mainloop啊 但是会报错
                time.sleep(0.5)

        self.rsvtimer.cancel()
        self.logger.critical('控制平台退出')


if __name__=='__main__':
    logger_main = logging.getLogger(__name__)
    logger_main.setLevel(level=logging.DEBUG)
    tmpC = CmdModule(('127.0.0.1',20000), [] ,logger_main)
    tmpC.newdev(1)
    tmpC.newapp(1, None)
    tmpC.newnet(1, None)
    tmpC.newlnk(1, None, 0)
    tmpC.newlnk(1, None, 1)
    tmpC.newlnk(1, None, 2)
    tmpC.newphy(1, 0)
    tmpC.newdev(2)
    tmpC.newdev(3)
    tmpC.root.mainloop()
    print('主控推出')