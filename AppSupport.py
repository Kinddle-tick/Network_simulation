import threading
import socket
import tkinter as tk
import tkinter.filedialog

import logging
import os
import re
import random
import time

import json
import base64
import gzip
from io import BytesIO


'''
应用层协议如下：
1字节         类型         Type     1表示广播 其他的都是单播
1字节         目的设备号   DDev
1字节         本地设备号   SDev
0~500字节     数据主体     Data

其他默认单播
'''

class AppModule(threading.Thread):
#----------------------------------------------下面是初始化函数——————————————————————————

    def __init__(self,Dev:int,Entity:int,Host:str='127.0.0.1',cmd_addr=None,x=0,y=0,daemon=True,
                 filename='ne.txt',logger=None):
        super().__init__(daemon=daemon)
        #处理地址问题
        self.Host=Host
        self.up_addr=None       #一般是没有上层端口的
        self.local_addr=(Host,10400+1000*Dev+Entity)
        self.Dev=Dev
        self.Layer ='APP'
        self.Entity = Entity
        self.lower_addr=[]
        self.cmd_addr=cmd_addr

        self.nefilename = filename

        self.buffer=[]#收到的信息缓存

        #服务于可视化的变量
        self.queue_log_show=[]
        self.log_show_tmp= ''#消息栏展示的内容
        self.flag=['-','\\','|','/']
        self.flag_state=0

        #日志设定
        self.logger=logger

        #初始化时候可能用到的变量
        self.txt1 = None
        self.txt2 = None
        self.txt3 = None

        #窗口位置
        self.winx = x#310
        self.winy = y#350

        #控制文件发送
        self.access_send={}
        self.rcv_no={}
        self.FileResendSet=8    #文件传输时 多久试图重传一次 这个时间需要和分组大小权衡...
        self.FileDataCut  =500  #文件分组大小

    def read_ne(self,filename):
        with open(filename,mode='r') as ne:
            nowdev=-1
            layer =''
            layer_no=-1
            Entity_ID=-1
            tmpupper = {0:None,1: None, 2: None, 3: None,4: None,5:None}# PHY LNK NET APP 保存最近更新的模块端口号
            while True:
                tx = ne.readline()  # 读取一行保存在tx里面
                if tx == '':  # 只有文件末尾才会有这种情况
                    break

                tx = re.split('#', tx)[0]  # 去除行末注释
                if re.sub('\s', '', tx) == '':  # 空行或者开头#都会直接忽略掉  这里的#是比较灵活的
                    continue

                elif not re.search('--',tx) and not re.search('=',tx):
                    tmp_ett = [i for i in re.split('\s+', tx) if i != '']
                    upflag=False
                    for txi in tmp_ett:
                        if re.match('\d', txi) != None:
                            nowdev = int(txi)
                        else:
                            layer = re.search('[a-zA-Z]+', txi).group()
                            layer_no=self.map_Lev(layer)
                            Entity_ID = int(re.search('[0-9]+', txi).group())
                            if layer_no==self.map_Lev(self.Layer) and \
                                tmpupper[layer_no] == 10000+1000*self.Dev+100*self.map_Lev(self.Layer)+self.Entity:#与本模块同层 而且tmpupper内部保存的刚好是本模块数据
                                #logging.info('模块上下层处理完毕')
                                return
                            tmpupper[layer_no]=10000+1000*nowdev+100*layer_no+Entity_ID
                        if nowdev != self.Dev:
                            break #只要读了每行第一个元素就能确定这一行是不是我们期待的设备号
                        else:#在我们期待的设备号中如何处理每个模块
                            if layer ==self.Layer and Entity_ID == self.Entity:
                                self.lower_addr.append((self.Host, tmpupper[layer_no-1]))
                                self.up_addr =(self.Host, tmpupper[layer_no+1])
                                upflag=True
                            elif upflag:
                                self.up_addr =(self.Host,tmpupper[layer_no])
                                upflag=False
                            elif txi==tmp_ett[-1] and layer_no+1==self.map_Lev(self.Layer) :#处于本行末尾 而且是本模块的上一层
                                self.lower_addr.append((self.Host, tmpupper[layer_no]))

    def map_Lev(self,layer:str):

        if layer == 'PHY':
            return  1
        elif layer == 'LNK':
            return  2
        elif layer == "NET":
            return  3
        elif layer == 'APP':
            return  4
        else:
            logging.warning("在匹配层次时出错")
            return 0

    # def add_lower(self,addr):
    #     self.lower_addr.append(addr)
    # def add_up(self,addr):
    #     self.up_addr=addr
#----------------------------------------------文件处理--------------------------------------------
    def b2j_file_encode(self,data:bytes):
        #data=b''
        buffer=BytesIO()#开辟假文件
        with gzip.GzipFile(mode='wb',fileobj=buffer) as f:
            f.write(data)
        compress_data = buffer.getvalue()
        jsondata=str(base64.b64encode(compress_data))[2:-1]
        buffer.close()
        return jsondata
    def j2b_file_decode(self,data:str):
        bytes_64=base64.b64decode(data)
        buffer=BytesIO(bytes_64)
        with gzip.GzipFile(mode='rb', fileobj=buffer) as f:
            uncompress_data=f.read()
        buffer.close()
        return uncompress_data
#----------------------------------------------应用层协议--------------------------------------------
    def protocol_decode(self,by:bytes):
        rtn={}
        rtn['Type']=by[0]
        rtn['DDev']=by[1]
        rtn['SDev']=by[2]
        rtn['Data']=by[3:].decode()
        return rtn
    def protocol_encode(self,s:str='',Type=1,DDev=None,SDev=None,rule='utf-8'):
        '''
        可以直接发送 不是01字符串
        :param s: 数据
        :param Type: 发送类型
        :param SDev: 发送设备号
        :param DDev: 接收设备号
        :param rule: 编码规则
        :return: 编码后的byte
        '''
        rtn=b''
        type=hex(int(Type))[2:].rjust(2, '0')
        rtn+=bytes.fromhex(type)
        if DDev!=None:
            dev=hex(int(DDev))[2:].rjust(2, '0')
        else:
            dev ='ff'

        rtn += bytes.fromhex(dev)
        if SDev==None:
            SDev=self.Dev
        SDev=hex(int(SDev))[2:].rjust(2, '0')
        rtn += bytes.fromhex(SDev)
        #print(s.encode())
        rtn+=s.encode(rule)
        #print(rtn)#用于测试
        return rtn

#----------------------------------------------发送函数--------------------------------------------
    def main_send(self,so:socket,st:str='',Type=1,Dev=None):
        self.sendtocmd('s')

        if so == None:
            self.logger_add('错误的套接字端口，发送失败')
            self.sendtocmd('n')
            return True
        if st == None:
            string=''
        else:
            string=st

        self.logger_add('※发送：--------------------')
        self.logger_add('Data：{}'.format(string)+'\n目的设备号：{}'.format('广播' if Type == 1 else Dev))
        msgsend=self.protocol_encode(string,Type=Type,DDev=Dev)
        for i in self.lower_addr:
            so.sendto(msgsend, i)

        self.logger_add('信息发送到下层了√')
        self.txt1.delete('1.0', 'end')
        self.txt1.insert(tk.END, self.log_show_tmp)
        self.log_show_tmp = ''

        self.sendtocmd('n')
        return True
    #文件发送
    def main_send_file_button(self, LST):#将发送列表传入 格式为[path,path,...]
        if self.txt3.get() == '':#面向连接的广播太疯狂了 我ban了
            tmp = '发送失败 请填写目的地址\n'
            self.txt1.insert(tk.END, tmp)
            return
        List=[i for i in LST if re.sub('\s','',i)]#留下有效的路径
        for path in List:
            # 给文件一个含有4位随机码的名字
            alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIGKLMNOPQRSTUVWXYZ0123456789'
            randomchar = ''.join([random.choice(alphabet) for i in range(0, 4)])
            oldname = os.path.basename(path)
            newname = os.path.splitext(oldname)[0] + randomchar + os.path.splitext(oldname)[-1]

            #首先建立连接（让对方开启一个等待接收该文件的缓存）
            request={'Type':'file','Name':newname,'Ctrl':0,'No':0,'Data':'request'}
            json_request=json.dumps(request)
            self.main_send(self.socket, json_request, 0 if self.txt3.get() != '' else 1,
                           self.txt3.get() if self.txt3.get() != '' else None)
            self.access_send[newname] = False
            sendtime = time.time()
            while self.access_send[newname] != 1:  # 等待确认

                if time.time() - sendtime > self.FileResendSet:
                    print("设备号{}应用层重传了序号{}".format(self.Dev,0))
                    sendtime = time.time()
                    self.main_send(self.socket, json_request, 0 if self.txt3.get() != '' else 1,
                                   self.txt3.get() if self.txt3.get() != '' else None)

            # 发送过程中
            with open(path, mode='rb') as fsend:
                count=2
                gzipbuffer=BytesIO()
                tmps=fsend.read()
                with gzip.GzipFile(mode='wb', fileobj=gzipbuffer) as f:
                    f.write(tmps)#将读到的内容全部压缩到虚拟文件gzipbuffer中去

                compress_data = gzipbuffer.getvalue()
                gzipbuffer.close()

                jsondata = str(base64.b64encode(compress_data))[2:-1]

                DataSendList=re.findall('.{1,%d}'%self.FileDataCut,jsondata)
                maxsend=len(DataSendList)
                for i in DataSendList:
                    data = {'Type': 'file', 'Name': newname, 'Ctrl': 0, 'No': count, 'Data': i}
                    json_data=json.dumps(data)

                    tmp = '发送中,共发送了{}帧,总共需要发送{}帧(不计控制帧）'.format(count - 2, maxsend)
                    self.log_show_tmp += tmp
                    self.main_send(self.socket,json_data,0 if self.txt3.get()!='' else 1,
                                self.txt3.get() if self.txt3.get() != '' else None)
                    self.access_send[newname] = False
                    sendtime=time.time()

                    #在发送确认之前都会呆在这个循环
                    while self.access_send[newname] != count:#等待收到刚刚发送的序号的确认
                        if self.access_send[newname] > count:#提高一下容错 也可能随着代码的健壮不会出现这种情况
                            self.access_send[newname] = False
                            continue
                        if time.time()-sendtime >self.FileResendSet:
                            print("设备号{}应用层重传了序号{}".format(self.Dev, count))

                            self.main_send(self.socket, json_data, 0 if self.txt3.get() != '' else 1,
                                           self.txt3.get() if self.txt3.get() != '' else None)
                            sendtime = time.time()
                    count+=1

            # 发送结束 发送quit促使对方释放缓存 解压等 也需要等待对方的回应
            quit = {'Type': 'file', 'Name': newname, 'Ctrl': -1, 'No': count, 'Data': 'quit'}
            json_quit=json.dumps(quit)
            self.main_send(self.socket, json_quit, 0 if self.txt3.get() != '' else 1,
                           self.txt3.get() if self.txt3.get() != '' else None)
            self.access_send[newname] = False
            sendtime = time.time()
            # 获得确认之前
            while self.access_send[newname] != count :  # 等待收到刚刚发送的序号的确认(回应
                if self.access_send[newname] > count:
                    self.access_send[newname] = False
                    continue
                if time.time() - sendtime > self.FileResendSet:
                    print("设备号{}应用层重传了序号{}".format(self.Dev, count))
                    sendtime = time.time()
                    self.main_send(self.socket, json_quit, 0 if self.txt3.get() != '' else 1,
                                   self.txt3.get() if self.txt3.get() != '' else None)

            self.logger.info('发送完毕,共发送了{}帧'.format(count))
            tmp='发送完毕,共发送了{}帧'.format(count)
            self.txt1.insert(tk.END, tmp)
            return

#----------------------------------------------下面是接收函数——————————————————————————
    def main_recv(self,data,addr):
        self.logger_add('★接收到了报文--------------------')
        print('★接收到了报文------------------------------')
        self.logger_add('收到的内容为：\n'+str(data))
        msgdic=self.protocol_decode(data)
        if msgdic!=None:
            Type=msgdic['Type']
            DDev=msgdic['DDev']
            SDev=msgdic['SDev']
            data=msgdic['Data']
        else:
            return False
        self.logger_add('经过解码得到以下内容参考：' )
        self.logger_add('信息类型：{},源设备号：{},目的设备号：{}'.format(('广播' if Type%2 == 1 else '单播'),SDev,DDev))
        datadic=json.loads(data)
        if datadic['Type']=='string':
            string=self.j2b_file_decode(datadic['Data']).decode()
            self.logger_add('数据类型：字符串 解码内容：{}'.format(string))

        elif datadic['Type'] =='file':
            print('设备{}收到了文件 序号为{} 来自{}'.format(self.Dev,datadic['No'],'发送方' if datadic['Ctrl']==0 else "接收方"))
            oldname=datadic['Name']
            newname=os.path.splitext(oldname)[0]+'[设备{}接受]'.format(self.Dev)+os.path.splitext(oldname)[-1]
            newname_gz=os.path.splitext(oldname)[0]+'[设备{}接受].gz'.format(self.Dev)
            if datadic['Ctrl']==0:#收到了内容
                if datadic['No']==0:            #request
                    self.rcv_no[oldname] = 1    #达成共识
                    access = {'Type': 'file', 'Name': oldname, 'Ctrl': 1, 'No': 1, 'Data': ''}
                elif  datadic['No'] == self.rcv_no[oldname]+1:  #这个内容是自己需要的部分(已收到的部分的下一个
                    bytes_64 = base64.b64decode(datadic['Data'])
                    with open(newname_gz,mode='ab') as f:
                        f.write(bytes_64)
                        self.logger_add('将文件保存在：{}'.format(newname_gz))
                        print('将文件保存在：{}'.format(newname_gz))
                    access={'Type':'file','Name':oldname,'Ctrl':1,'No':datadic['No'],'Data':''}
                    self.rcv_no[oldname]=datadic['No']
                elif datadic['No']==self.rcv_no[oldname]:       #不是自己需要的部分（比如重复帧)告诉对方自己需要的内容到底收到了没有
                    print('是重复的'.format(datadic['No'], self.rcv_no[oldname]))
                    access = {'Type': 'file', 'Name': oldname, 'Ctrl': 1, 'No': self.rcv_no[oldname], 'Data': ''}
                    self.rcv_no[oldname] = datadic['No']
                else:
                    return
                self.main_send(self.socket, json.dumps(access), Type=Type, Dev=SDev)

            elif datadic['Ctrl']==1:    #收到了确认
                self.access_send[oldname]=datadic['No']
            elif datadic['Ctrl']==-1:   #收到了关闭确认
                access = {'Type': 'file', 'Name': oldname, 'Ctrl': 1, 'No': datadic['No'], 'Data': ''}
                self.main_send(self.socket, json.dumps(access), Type=Type, Dev=SDev)
                if oldname in self.rcv_no:
                    #结束这个文件
                    x=self.rcv_no.pop(oldname)
                    self.logger_add('接收完毕 解压 总共{}帧'.format(x+1))
                    print('接收完毕 解压 总共{}帧'.format(x))
                    with gzip.GzipFile(newname_gz,mode='rb') as f:
                        uncompress_data = f.read()
                    os.remove(newname_gz)
                    with open(newname, mode='wb') as getfile:
                        getfile.write(uncompress_data)
                        self.logger_add('将文件解压到：{}'.format(newname))
                        print('将文件解压到：{}'.format(newname))

        return True

    def rcv_FromSocket_loop(self, f=0.25):
        '''
        开始尝试接受内容，接收到的消息会原封不动的保存self.buffer中，用其他函数来提取。
        :param f: 检查接口的频率 单位是秒
        :return:None
        '''
        self.rcvtimer = threading.Timer(f, self.rcv_FromSocket_loop, (f,))
        self.rcvtimer.start()
        try:
            tmp=self.socket.recvfrom(65536)
            assert len(tmp)!=0
        except:
            return

        data,addr=tmp#控制层的包优先级最高 不用去buffer排队直接处理
        if addr == self.cmd_addr :
            if data==b'exit\0':
                self.root.destroy()
                return
            else:
                self.handle_cmd(data)
        else:
            self.buffer.append(tmp)
        return

    def rcv_Frombuffer_loop(self, f=0.25):
        timer = threading.Timer(f, self.rcv_Frombuffer_loop, (f,))
        if len(self.buffer)!=0:
            rtn = self.buffer.pop(0)
            timer.start()
            try:
                self.logger.debug('*-*-*-*-*-*-*设备{}应用层收到了一个帧*-*-*-*-*-*-*'.format(self.Dev))
                self.sendtocmd('r')

                self.main_recv(*rtn)
                self.logger_clear()

                self.sendtocmd('n')
                self.logger.debug('*-*-*-*-*-*-*设备{}应用层处理了一个帧*-*-*-*-*-*-*\n'.format(self.Dev))
            except Exception as z :
                self.logger.warning("设备{}应用层接受出错，原因：{}".format(self.Dev,z))
                print(z)
        else:
            timer.start()
        return
#----------------------------------------------下面是可视化界面函数——————————————————————————
    #又多又烦 建议不看
    def logger_add(self,*args,end='\n'):
        for i in args:
            self.log_show_tmp+= i + end
    def logger_clear(self):
        #尝试将缓存的log_show_tmp加入队列，显示队列个数
        if self.log_show_tmp!='':
            self.queue_log_show.append(self.log_show_tmp)
        self.Lab_buffer.configure(text="queue:{}".format(len(self.queue_log_show)))
        self.log_show_tmp= ''
    def logger_show(self):
        #展示队列第一个 并显示展示后的队列个数
        if len(self.queue_log_show)!=0:
            tmp=self.queue_log_show.pop(0)
        else:
            tmp="缓存为空"
        self.Lab_buffer.configure(text="queue:{}".format(len(self.queue_log_show)))
        self.txt1.delete('1.0', 'end')
        self.txt1.insert(tk.END, tmp)

    def addaddr(self,Lstbox):
        initpath=os.getcwd()
        path = tk.filedialog.askopenfilename(initialdir=(initpath))
        if path != '':
            if Lstbox.curselection() == ():
                Lstbox.insert(Lstbox.size(), path)
            else:
                Lstbox.insert(Lstbox.curselection(), path)
        else:
            return None

    def newfile(self,root):
        winfile = tk.Toplevel(root)
        winfile.geometry('250x210')
        winfile.wm_attributes('-topmost', 1)
        winfile.title('发送文件')
        lb = tk.Label(winfile, text='文件列表', fg='black', font=("黑体", 9), anchor=tk.W)
        lb.place(relx=0, rely=0, height=30, width=190)

        frm1 = tk.Frame(winfile)
        frm1.place(x=0, y=30, relheight=1, relwidth=1, height=-31, width=-70)

        Lstbox1 = tk.Listbox(frm1)
        Lstbox1.place(x=0, y=0, relheight=1, relwidth=1)

        frm2 = tk.Frame(winfile)
        frm2.place(relx=1, rely=1, x=-70, y=-120, width=70, height=120)

        btn2 = tk.Button(frm2, text='添加路径', command=                    \
                         lambda: self.addaddr(Lstbox1))
        btn2.place(relx=0, rely=0, relheight=0.25, relwidth=1)

        btn3 = tk.Button(frm2, text='删除路径', command=                    \
                         lambda: Lstbox1.delete(Lstbox1.curselection())     \
                         if Lstbox1.curselection() != ()                    \
                         else None)
        btn3.place(relx=0, rely=0.25, relheight=0.25, relwidth=1)

        btn4 = tk.Button(frm2, text='  发送  ', command=lambda: self.button_send_file(Lstbox1.get(0, tk.END)))
        btn4.place(relx=0, rely=0.5, relheight=0.25, relwidth=1)

        btn5 = tk.Button(frm2, text='  退出  ', command=winfile.destroy)
        btn5.place(relx=0, rely=0.75, relheight=0.25, relwidth=1)

    def newinfo(self,root):
        winNew = tk.Toplevel(root)
        winNew.geometry('200x60')
        winNew.title('新窗体')
        lbinfo = tk.Label(winNew, text='上层地址：{}\n本地地址：{}\n下层地址：{}'.format(self.up_addr, self.local_addr, self.lower_addr),
                          fg='black', font=("黑体", 9), relief=tk.GROOVE)
        lbinfo.place(relx=0, rely=0, relheight=1, relwidth=1)
    def newroot(self, funcSend=None, funcRsv=None,x=0,y=0):
        '''
        配置一个窗口 并且将窗口对应的按钮绑定好
        绑定方法：没有参数直接写函数名 有参数使用lambda函数 lambda:func(xxx)
        窗口的大部分内容都不能自定义（简洁起见）
        可以通过对四个函数的合理搭配来取代传统的case方法
        要运行这个窗口 请使用root.mainloop() #root是该函数的返回值
        :return: 这个窗口本身root
        '''
        root = tk.Tk()

        root.title('设备{}应用层实体{}界面'.format(self.Dev,self.Entity))
        root.attributes("-alpha", 0)
        root.geometry('300x300+{}+{}'.format( x,y ))  # 这里的乘号不是 * ，而是小写英文字母 x

        frm1 = tk.Frame(root)
        frm1.place(relx=0, rely=0, relheight=1, relwidth=1, height=-100)

        lb1 = tk.Label(frm1, text='消息', fg='black', font=("黑体", 9), anchor=tk.W)
        lb1.place(relx=0, rely=0, height=30, relwidth=0.25)

        # cv=tk.Canvas(frm1,bg='blue')
        # v.create_rectangle(10,1,20,10)
        # cv.place(relx=10,rely=0,relheight=0.1,relwidth=0.25)

        self.txt1 = tk.Text(frm1)
        self.txt1.place(relx=0,rely=0,y=30,relheight=1,height=-30,relwidth=1)

        btninfo = tk.Button(frm1, text='属性', relief=tk.GROOVE, command=lambda: self.newinfo(root))  #
        btninfo.place(relx=0.8, rely=0, height=30, relwidth=0.2)

        btnbytes = tk.Button(frm1, text='文件', relief=tk.GROOVE, command=lambda: self.newfile(root))  #
        btnbytes.place(relx=0.6, rely=0, height=30, relwidth=0.2)

        frm = tk.Frame(root)
        frm.place(relx=0, rely=1, height=100, relwidth=1, y=-100)

        lb2 = tk.Label(frm, text='发送信息', fg='black', font=("黑体", 9), anchor=tk.W)
        lb2.place(relx=0, rely=0, relheight=0.2, relwidth=0.25)

        self.txt2 = tk.Text(frm)
        self.txt2.place(relx=0, rely=0.2, relheight=0.8, relwidth=0.5)

        lb3 = tk.Label(frm, text='发送地址（设备号）', fg='black', font=("黑体", 9), anchor=tk.W)
        lb3.place(relx=0.5, rely=0, relheight=0.2, relwidth=0.5)

        self.txt3 = tk.Entry(frm, bg='#CCFFCC')
        self.txt3.place(relx=0.5, rely=0.2, relheight=0.2, relwidth=0.5)
        # self.txt3 = tk.Text(frm)
        # self.txt3.place(relx=0.5, rely=0.2, relheight=0.5, relwidth=0.5)

        btn1 = tk.Button(frm, text='发送', command=funcSend, relief=tk.GROOVE)
        btn1.place(relx=0.5, rely=0.4, relheight=0.30, relwidth=0.25)

        btn2 = tk.Button(frm, text='接收', command=funcRsv, relief=tk.GROOVE)  # lambda:func('btn2')
        btn2.place(relx=0.5, rely=0.7, relheight=0.30, relwidth=0.25)

        # btn3 = tk.Button(frm, text='刷新', command=funcFls)
        # btn3.place(relx=0.5, rely=0.7, relheight=0.30, relwidth=0.25)
        # btn3.config(command=lambda: func('btn3'))
        self.Lab_buffer = tk.Label(frm, text='queue:0', relief=tk.GROOVE)
        self.Lab_buffer.place(relx=0.75, rely=0.4, relheight=0.30, relwidth=0.25)

        btn4 = tk.Button(frm, text='退出', command=root.destroy, relief=tk.GROOVE)
        btn4.place(relx=0.75, rely=0.7, relheight=0.30, relwidth=0.25)

        self.root = root
        return self.root

    def button_send(self):
        self.logger_add('当前处于应用层 设备号：{}'.format(self.Dev),'发送中...')
        self.logger.debug('###################设备{}应用层发送了一个帧###################'.format(self.Dev))
        msg=self.txt2.get('1.0',tk.END)
        if msg == '\n':
            return
        else:
            Gzmsg=self.b2j_file_encode(msg.encode())
            data = {'Type': 'string', 'Name': None, 'Data': Gzmsg}
            jsons=json.dumps(data)
        ddev=self.txt3.get()
        if ddev == '':
            ddev=None
        Type=0
        if ddev==None:#没有写设备号表示是广播
            Type=1
        try:
            self.main_send(self.socket,jsons,Type=Type,Dev=ddev)
        except:
            self.logger.error('发送失败了')
    def button_send_file(self,pathlist):
        a=threading.Thread(target=self.main_send_file_button,args=(pathlist,))
        #之所以使用线程，是因为如果不用主线程会卡在发送按钮上直到传完为止
        a.start()

    def sendtocmd(self,color):
        if color=='s':
            tmp='#FF0033'
        elif color=='r':
            tmp='#33FF33'
        elif color=='n':
            tmp='#DDDDDD'
        else:
            tmp=color
        self.socket.sendto(tmp.encode(),self.cmd_addr)
    def handle_cmd(self,data):
        if data==b'show\0':
            self.root.attributes("-alpha",1)
        elif data==b"hide\0":
            self.root.attributes("-alpha",0)

#----------------------------------------------下面是主函数——————————————————————————

    def run(self):
        self.read_ne(self.nefilename)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setblocking(False)
            s.bind(self.local_addr)
            self.socket=s
            self.rcv_FromSocket_loop(1)
            root = self.newroot(funcSend=self.button_send,funcRsv=self.logger_show,x=self.winx,y=self.winy)
            self.rcv_Frombuffer_loop(0.25)

            root.mainloop()
            self.rcvtimer.cancel()



if __name__=='__main__':
    HOST = '127.0.0.1'
    PORT_LOCAL = 11200
    PORT_LOWER = [11100]

    upper_addr = None
    local_addr = (HOST, PORT_LOCAL)
    lower_addr = [(HOST, i) for i in PORT_LOWER]  # 最多十个

    tst=AppModule(1,0,daemon=False)

    tst.start()
    tst.root.attributes('-alpha', 1)
    print('w')



