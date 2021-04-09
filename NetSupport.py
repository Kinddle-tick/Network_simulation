import threading
import socket
import tkinter as tk

import time
import random
import re
import json
'''
网络层协议如下：
2字节     序号         No       每一个从应用层来的崭新的帧，都会随机到一个序号
1字节     类型         Type     奇数广播 偶数单播 01代表字符串
1字节     目的设备号    DDev
1字节     本地设备号    SDev
?字节     数据主体      Data

其他默认单播
'''

class NetModule(threading.Thread):
#----------------------------------------------下面是初始化函数——————————————————————————

    def __init__(self, Dev: int, Entity: int, Host: str = '127.0.0.1', cmd_addr=None, x=0, y=0, daemon=True,
                 filename='ne.txt',logger=None):
        super().__init__(daemon=daemon)
        self.Host=Host
        self.nefilename=filename
        self.up_addr = None  # 一般是没有上层端口的
        self.local_addr = (Host, 10300 + 1000 * Dev + Entity)
        self.Dev = Dev
        self.Layer='NET'
        self.Entity = Entity
        self.lower_addr = []  # 在这个网元模型中一个网元里只有一个网络层设备和一个应用层设备所以只拿了第一个
        self.cmd_addr = cmd_addr

        self.winx=x
        self.winy=y

        self.buffer=[]#收到的信息缓存
        self.buffer_send = []  # 发送的信息的暂时缓存 格式（序号，发送的原文）

        self.log_show= ''#消息栏展示的内容
        self.logger = logger

        self.txt1 = None

        self.OutTimeAddr_DV = 300
        self.OutTimeAddr_auto = 30
        self.MaxRegetTime = 20  # 当收到同一个帧两次的时候 会根据这个时间判断是否是重复产生的帧并删掉

        self.addrlist = [(self.Dev, ('127.0.0.1', 66666), time.time(), 0)]  # 每个元素的格式：（目的设备号，下层地址，时间戳,跳数）
        self.history = []  # 每个元素的格式：（某帧序号，时间戳）防止广播风暴的简单方法

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
                                self.add_lower((self.Host, tmpupper[layer_no-1]))
                                self.add_up((self.Host, tmpupper[layer_no+1]))
                                upflag=True
                            elif upflag:
                                self.add_up((self.Host,tmpupper[layer_no]))
                                upflag=False
                            elif txi==tmp_ett[-1] and layer_no+1==self.map_Lev(self.Layer) :#处于本行末尾 而且是本模块的上一层
                                self.add_lower((self.Host, tmpupper[layer_no]))

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
            return 0

    def add_lower(self,addr):
        self.lower_addr.append(addr)
    def add_up(self,addr):
        self.up_addr=addr
#---------------------------------------------关于地址表的部分-----------------------------------------------
    def addr_flesh(self):
        #根据当前的时间删除一些反向学习的内容
        nowtime=time.time()
        for i in self.addrlist:
            if i[0]==self.Dev:
                continue
            if nowtime-i[2]>=self.OutTimeAddr_DV or (nowtime-i[2]>=self.OutTimeAddr_auto and i[3]==-1 ):#双标 反向学习的有效时间和动态路由的不同
                self.addrlist.remove(i)
        return True

    def addr_add(self,Dev,addr,jump=-1):#jump是从这个设备到另一个设备要经过多少个物理层。
        if Dev==self.Dev or Dev==255:
            return False
        self.addr_flesh()
        nowtime=time.time()
        rtn=False
        find=False
        self.logger.info("设备{}网络层试图增加这条记录：{}".format(self.Dev,[Dev,addr,jump]))
        for i in self.addrlist:
            if i[0]==Dev:               #如果有关于这个设备号的记录
                find=True
                if i[3]==-1:                 #记录是反向学习的
                    if jump ==-1:                #添加的记录是反向学习的
                                                    #仅仅更新时间 但是记录的端口号以老的为准
                        self.addrlist.remove(i)
                        self.addrlist.append((Dev, i[1], nowtime, -1))
                        self.logger.info("{}".format(i))
                        self.logger.info("原纪录为反向学习 更新时间")
                        rtn= False
                    else:                       #添加的记录是动态路由算法的
                                                    #动态路由算法有更高优先权 记录动态路由算法的端口号
                        self.addrlist.remove(i)
                        self.addrlist.append((Dev, addr, nowtime, jump))
                        self.logger.info("原纪录为反向学习 更新DV路线")
                        rtn= True
                else:                       #记录是 动态路由算法学习 的(jump!=0)
                    if jump == -1:              #添加的是反向学习
                        if i[1]==addr and i[3]==jump:              #端口号一致且跳数一致
                            self.addrlist.remove(i)
                            self.addrlist.append((Dev, i[1], nowtime, jump))
                            self.logger.info("\t原纪录为反向学习 更新时间（确信度上升了）")
                    elif i[1]==addr:              #记录的端口号和添加的端口号一样
                        if i[3]<=jump:              #记录的端口号跳数不大于添加的
                                                        #保留原来的 更新时间
                            self.addrlist.remove(i)
                            self.addrlist.append((Dev, i[1], nowtime, i[3]))
                            self.logger.info("原纪录为动态学习 保留原有")
                            rtn= False
                        else:                       #记录的端口号跳数大于添加的
                                                        #更新记录
                            self.addrlist.remove(i)
                            self.addrlist.append((Dev,addr,nowtime,jump))
                            self.logger.info("原纪录为动态学习 更新跳数")
                            rtn = True
                    else:                       #记录的端口号和添加的端口号不一致
                        if i[3]<=jump:              #记录的端口号跳数不大于添加的
                                                        #保留原来的，丢弃这条记录
                            self.logger.info("原纪录为动态学习 丢弃")
                            rtn = False
                        else:                       #记录的端口号跳数大于添加的
                                                        #更新记录
                            self.addrlist.remove(i)
                            self.addrlist.append((Dev,addr,nowtime,jump))
                            self.logger.info("原纪录为动态学习 更新记录")
                            rtn = False

        #如果压根没有关于这个设备的记录
        if find==False:
            self.addrlist.append((Dev,addr,nowtime, jump))#一个崭新的地址！
            self.logger.info("没有找到该端口的记录 直接添加")
            if jump==-1:
                rtn=False
            else:
                rtn=True

        # self.logger.info("设备{}网络层当前地址表为：".format(self.Dev))
        # for i in self.addrlist:
        #     self.logger.info("{}".format(i))
        self.logger.info("{}".format('\t更新了路由表'if rtn==True else '没更新路由表'))
        return rtn

    def addr_find(self,Dev):
        self.addr_flesh()
        for i in self.addrlist:
            if i[0]==Dev:
                return i[1]
        return None


    def history_add(self,NO):
        #尝试向history中添加记录 更新时间
        nowtime=time.time()
        rtn=True
        for i in self.history:
            if i[0]==NO:
                self.history.remove(i)
        self.history.append((NO,nowtime))
        return rtn

    def history_check(self,NO):
        #查询是否有着历史记录 在时间限制之内（即判定为重复）则返回False 否则为True(未重复) 都会顺便更新时间
        nowtime = time.time()
        rtn = True
        for i in self.history:
            if i[0] == NO:
                if nowtime - i[1] <= self.MaxRegetTime:
                    rtn = False
                else:
                    rtn = True
                self.history.remove(i)
        self.history.append((NO, nowtime))
        return rtn

    def getNO(self):
        '''
        从0~65535获得一个从未使用过的NO 包括接受历史 发送缓存都没有
        有冲突的可能性，但低负载应该还好
        避免锁死只尝试一百次
        :return: NO:int
        '''
        i=0
        while i!=100:
            NO=random.randint(0,65535)
            for j in self.history:
                if j[0]==NO :
                    if time.time()-j[1]>=self.MaxRegetTime:
                        self.history.remove(j)
                    else:
                        i+=1
                        continue
            for j in self.buffer_send:
                if NO == j[0]:
                    i+=1
                    continue
            return NO
        return None
#----------------------------------------------应用层协议--------------------------------------------
    def protocol_decode_up(self, Data:bytes):
        rtn={}
        rtn['Type'] = Data[0]
        rtn['DDev'] = Data[1]
        rtn['SDev'] = Data[2]
        rtn['Data'] = Data[3:]
        return rtn

    def protocol_decode_low(self, Data:bytes):
        rtn={}
        rtn[ 'No' ] = Data[0] * 256 + Data[1]
        rtn['Type'] = Data[2]
        rtn['DDev'] = Data[3]
        rtn['SDev'] = Data[4]
        rtn['Data'] = Data[5:]
        return rtn

    def protocol_encode(self, Data:bytes=b'', Type=1, DDev=None, SDev=None,No=None):
        '''
        可以直接发送 不是01字符串 向上发送不需要写No，向下发送则要写
        :return: 编码后的byte
        '''
        rtn=b''

        if No != None and No < 65536:#上层协议的不同来控制发送的内容
            no=hex(int(No))[2:].rjust(4, '0')
            rtn+=bytes.fromhex(no)

        type=hex(int(Type))[2:].rjust(2, '0')
        rtn+=bytes.fromhex(type)

        if DDev!=None:
            ddev=hex(int(DDev))[2:].rjust(2, '0')
        else:
            ddev ='ff'
        rtn += bytes.fromhex(ddev)

        if SDev==None:
            SDev=self.Dev
        sdev=hex(int(SDev))[2:].rjust(2, '0')
        rtn += bytes.fromhex(sdev)
        #print(s.encode())
        rtn+=Data
        #print(rtn)#用于测试
        return rtn

#----------------------------------------------发送函数--------------------------------------------
    def send2up(self,Data:bytes=b'',Type=1,DDev=None,SDev=None):
        self.sendtocmd('s')
        msgsend=self.protocol_encode(Data, Type, DDev, SDev)
        self.socket.sendto(msgsend,self.up_addr)#毫无疑问只有一个上层
        self.sendtocmd('n')

    def send2low(self,addr:list,Data:bytes=b'',Type=1,DDev=None,SDev=None,No=65535):
        self.sendtocmd('s')
        bystr=self.protocol_encode(Data, Type, DDev, SDev,No)
        for i in addr:
            self.socket.sendto(bystr, i)
        self.sendtocmd('n')
        return True

#----------------------------------------------下面是接收函数——————————————————————————
    def main_recv(self,data,addr):
        if addr == self.up_addr:
            self.logger.debug('设备{}网络层 收到的是上层帧 端口号{} '.format(self.Dev,addr[1]))
            msgdic=self.protocol_decode_up(data)
        elif addr in self.lower_addr:
            self.logger.debug('设备{}网络层 收到的是下层帧 端口号{}'.format(self.Dev,addr[1]))
            msgdic=self.protocol_decode_low(data)
        else:
            self.logger.debug('设备{}网络层 收到的帧未知来源 端口号{}'.format(self.Dev,addr[1]))
            return True

        if msgdic!=None:#方便后面的调用
            Type=msgdic['Type']
            DDev=msgdic['DDev']
            SDev=msgdic['SDev']
            Data=msgdic['Data']
        else:
            return True
        self.logger.debug('设备{}网络层 收到的帧解析完成'.format(self.Dev))
        if addr==self.up_addr:
            if DDev==SDev:
                self.logger.debug('设备{}网络层 试图上传'.format(self.Dev))
                self.send2up(Data,Type,DDev,SDev)
                self.logger_add('从上层端口{}获得了帧，发送给本设备，回传'.format(addr))

            elif Type%2==1 or DDev==255:
                No = self.getNO()
                self.logger.debug('设备{}网络层 试图广播'.format(self.Dev))
                self.send2low(self.lower_addr, Data, Type, DDev, SDev, No)
                self.logger_add('从上层端口{}获得了帧，广播,序号为{}'.format(addr,No))
                self.logger.debug('设备{}网络层 广播完成'.format(self.Dev))

            else:
                self.logger.debug('设备{}网络层 试图单播'.format(self.Dev))
                Daddr=self.addr_find(DDev)
                No = self.getNO()
                if Daddr==None:#地址表没有内容 转发到下面的所有端口
                    self.send2low(self.lower_addr, Data, Type, DDev, SDev, No)
                    self.logger_add('从上层端口{}获得了帧，广播,序号为{}'.format(addr,No))
                else:#地址表有对应端口 转发到对应端口
                    self.send2low([Daddr],Data,Type,DDev,SDev,No)
                    self.logger_add('从上层端口{}获得了帧，单播设备{},序号为{}'.format(addr, DDev,No))
                self.logger.debug('设备{}网络层 单播完成'.format(self.Dev))


        elif addr in self.lower_addr:#来自下层
            No = msgdic['No']
            self.logger.debug('设备{}网络层 当前帧序号为{}'.format(self.Dev,No))
            if addr not in self.lower_addr:
                self.logger_add('从端口{}获得了帧，来源未知，丢弃，不记录'.format(addr))
                return True

            if not self.history_check(No):  # 未来得及停下的已经发送的帧 没有收到确认帧而重发的帧 因为NAK重发的帧 绕了一圈回来的帧
                self.logger.debug('设备{}网络层 判断为重复帧'.format(self.Dev))
                self.logger_add('从端口{}获得了帧，序号为{}，判断为重复'.format(addr, No))
                return True  # 重复帧安全性未可知（比如成环） 不进行学习 直接丢掉

                #反向地址学习
            self.addr_add(SDev,addr)
            self.logger.debug('设备{}网络层 反向地址学习'.format(self.Dev))

            if Type == 241:#动态路由规划
                self.logger.debug('设备{}网络层 是动态路由规划帧'.format(self.Dev))
                addrlist_change=self.rcv_DV(Data,addr)#专业处理这种数据
                if addrlist_change:
                    self.logger.debug('设备{}网络层 地址表更新了 分享地址表'.format(self.Dev))
                    self.send_DV(addr)



            elif DDev==self.Dev:#目的设备号就是自己的设备号 上传
                self.send2up(Data,Type,DDev,SDev)
                self.logger_add('从下层端口{}获得了帧,目的地址为自己，上传'.format(addr))
                self.logger.debug('设备{}网络层 上传给自己'.format(self.Dev))

            else:#不是自己的设备号就转发或者是因广播上传咯

                if DDev==255 or Type==1:#广播的内容上传一下
                    self.logger.debug('设备{}网络层 广播请求'.format(self.Dev))
                    self.send2up(Data,Type,DDev,SDev)
                    self.logger.debug('设备{}网络层 上传了广播内容'.format(self.Dev))

                    Daddrs = [i for i in self.lower_addr if i != addr]
                    if len(Daddrs) == 0:
                        self.logger_add('从下层端口{}获得了广播帧 序号{}，上传'.format(addr, No))

                    else:
                        self.send2low( Daddrs, Data, Type, DDev, SDev, No)
                        self.logger_add('从下层端口{}获得了广播帧 序号{},上传并广播转发到这些端口{}'.format(addr,No, Daddrs))
                        self.logger.debug('设备{}网络层 广播了一些帧'.format(self.Dev))
                    return True

                Daddr=self.addr_find(DDev)#先试图获得一个确定的单播端口
                if Daddr == addr:
                    self.logger_add('序{} 源{} 目{}，从端口{}获得了帧,试图发送给接受地址 拒绝'.format(No, SDev, DDev,addr[1]))
                    self.logger.debug('设备{}网络层 试图发送给接受地址 拒绝'.format(self.Dev))
                    return
                if Daddr == None:#无法确定 则向下广播 当然如果没办法广播了就丢弃 但是注意 这里广播的是单播帧
                    self.logger.debug('设备{}网络层 单播发送地址不确定'.format(self.Dev))
                    Daddrs = [i for i in self.lower_addr if i != addr]
                    if len(Daddrs)==0:
                        self.logger_add('从端口{}获得了单播帧，无处转发，丢弃'.format(addr))
                        self.logger.debug('设备{}网络层 无处转发 丢弃'.format(self.Dev))
                    else:
                        self.send2low(Daddrs,Data,Type,DDev,SDev, No)
                        self.logger_add('从端口{}获得了单播帧,寻址失败，广播转发到这些端口{}'.format(addr,Daddrs))
                        self.logger.debug('设备{}网络层 将单播帧广播到一些地方'.format(self.Dev))
                else:
                    self.logger.debug('设备{}网络层 单播发送地址确定'.format(self.Dev))
                    self.send2low( [Daddr], Data, Type, DDev, SDev, No)
                    self.logger_add('从端口{}获得了单播帧,单播转发到端口{}'.format(addr, Daddr))
        else:
            self.logger_add('收到未知来源的帧 丢弃')

        return True

    def rcv_FromSocket_loop(self, f=0.1):
        '''
        开始尝试接受内容，接收到的消息会原封不动的保存self.buff中，用其他函数来提取。
        同时也会停止接收内容直到重新启动该函数（可以在函数外人为控制每次接收到都直接启动,直接启动可能会比较ok
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

        data,addr=tmp#控制层的包优先级最高 不用排队直接处理
        if addr == self.cmd_addr :
            if data==b'exit\0':
                self.root.destroy()

            elif data==b'DVstart\0':
                self.send_DV()
            else:
                self.handle_cmd(data)

        else:
            self.buffer.append(tmp)
            self.Lab_buff.configure(text="buff:{}".format(len(self.buffer)))
        return

    def rcv_Frombuff_loop(self, f=0.25):
        timer = threading.Timer(f, self.rcv_Frombuff_loop, (f,))

        if len(self.buffer)!=0:
            rtn = self.buffer.pop(0)
            timer.start()
            self.Lab_buff.configure(text="buff:{}".format(len(self.buffer)))
            try:
                self.logger.debug('*-*-*-*-*-*-*设备{}网络层收到了一个帧*-*-*-*-*-*-*'.format(self.Dev))
                self.sendtocmd('r')
                self.main_recv(*rtn)
                self.sendtocmd('n')
                self.logger.debug('*-*-*-*-*-*-*设备{}网络层处理了一个帧*-*-*-*-*-*-*\n'.format(self.Dev))
            except Exception as z :
                self.logger.exception("设备{}网络层接受出错，原因：{}".format(self.Dev,z))
        else:
            timer.start()
        return

#----------------------------------------------下面是可视化界面函数——————————————————————————
    def logger_add(self,*args,end='\n'):
        for i in args:
            self.log_show+= i + end

        self.txt1.delete('1.0','end')
        self.txt1.insert(tk.END, self.log_show)

    def logger_clear(self):
        self.log_show= ''

    def newinfo(self,root):
        # global root
        winNew = tk.Toplevel(root)
        winNew.geometry('300x125')
        winNew.title('地址表信息')
        self.addr_flesh()
        temptxt =   '       端口号       目的地址  时间 跳数\n'
        self.addr_flesh()
        if len(self.addrlist)!=0:
            for i in self.addrlist:
                temptxt+='{}   {:}       {}s   {}\n'.format(i[1],i[0],int(time.time()-i[2]),i[3])
        self.txtinfo=tk.Text(winNew)
        self.txtinfo.delete('1.0','end')
        self.txtinfo.insert(tk.END,temptxt)
        self.txtinfo.place(relx=0, rely=0, relheight=1, relwidth=1)


    def newroot(self,x=0,y=0):
        '''
        配置一个窗口 并且将窗口对应的按钮绑定好
        绑定方法：没有参数直接写函数名 有参数使用lambda函数 lambda:func(xxx)
        窗口的大部分内容都不能自定义（简介起见）
        可以通过对四个函数的合理搭配来取代传统的case方法
        要运行这个窗口 请使用root.mainloop() #root是该函数的返回值
        :return: 这个窗口本身root
        '''
        root = tk.Tk()

        root.title('设备{}网络层实体{}界面'.format(self.Dev, self.Entity))
        root.attributes("-alpha", 0)
        root.geometry('300x150+{}+{}'.format(x,y))  # 这里的乘号不是 * ，而是小写英文字母 x

        frm1 = tk.Frame(root)
        frm1.place(relx=0, rely=0, relheight=1, relwidth=1, height=-40)

        lb1 = tk.Label(frm1, text='消息', fg='black', font=("黑体", 9), anchor=tk.W)
        lb1.place(relx=0, rely=0, height=30, relwidth=0.25)
        self.Lab_buff=tk.Label(frm1,text='buff:0',relief=tk.GROOVE)
        self.Lab_buff.place(relx=0.6,rely=0,height=30,relwidth=0.2)

        btninfo = tk.Button(frm1, text='地址表', relief=tk.GROOVE, command=lambda: self.newinfo(root))  #
        btninfo.place(relx=0.8, rely=0, height=30, relwidth=0.2)

        # cv=tk.Canvas(frm1,bg='blue')
        # v.create_rectangle(10,1,20,10)
        # cv.place(relx=10,rely=0,relheight=0.1,relwidth=0.25)

        self.txt1 = tk.Text(frm1)
        self.txt1.place(relx=0, rely=0, y=30, relheight=1, height=-20, relwidth=1)

        # relief=tk.GROOVE
        frminfo = tk.Frame(root)
        frminfo.place(relx=0, rely=1, height=40, relwidth=1, y=-40)

        lbinfo = tk.Label(frminfo, text='上层地址：{}\n本地地址：{}\n下层地址：{}'.format(self.up_addr, self.local_addr, self.lower_addr),
                          fg='black', font=("黑体", 9), anchor=tk.W, relief=tk.GROOVE)
        lbinfo.place(relx=0, rely=0, relheight=1, relwidth=1)

        self.root = root

        return self.root

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
#----------------------------------------------动态路由函数--------------------------------------------
    def rcv_DV(self,Data,addr):#要传入源地址的
        self.logger_add('从端口{}接收到了路由表'.format(addr))
        self.logger.debug("设备{}收到的内容为{}".format(self.Dev,Data))
        addrstr=Data.decode()
        addrload=json.loads(addrstr)
        rtn=False
        for i in addrload:
            jump=i["jump"]+1#若选择这条路 自己的跳数会在原来的基础上+1
            DDev=i['DDev']
            if jump==0:#过滤反向地址学习的部分
                continue
            else:
                flg=self.addr_add(DDev,addr,jump)#大多数情况都能在addr_add中解决 除了jump=0不能直接取分
                rtn=flg or rtn
        return rtn

    def send_DV(self,exceptaddr:list=None):
        self.logger_add('正在向除了{}的邻居转发自己的路由表'.format(exceptaddr))
        self.logger.info('***正在向除了{}的邻居转发自己的路由表'.format(exceptaddr))
        if exceptaddr == None:
            exceptaddr=[]
        formatjson=[]
        for i in self.addrlist:
            l = {'DDev': i[0], 'jump': i[3]}
            formatjson.append(l)
        addrstr=json.dumps(formatjson)
        Datasend=addrstr.encode()

        self.logger.info('设备{} 路由表发送内容{}'.format(self.Dev,addrstr))

        msgsend=self.protocol_encode(Datasend,Type=241,No=self.getNO())
        for i in self.lower_addr:
            if i not in exceptaddr:
                self.socket.sendto(msgsend,i)
                self.logger_add('向{}转发自己的路由表'.format(i))
                self.logger.info('向{}转发自己的路由表'.format(i))
        self.logger_add('转发完毕'.format(exceptaddr))
        self.logger.info('转发完毕'.format(exceptaddr))

        return True

#----------------------------------------------下面是主函数——————————————————————————

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(self.local_addr)
            s.setblocking(False)
            self.read_ne(self.nefilename)
            self.socket=s

            self.rcv_FromSocket_loop(0.5)
            self.root = self.newroot(x=self.winx,y=self.winy)

            self.rcv_Frombuff_loop(0.25)
            self.root.mainloop()
            self.rcvtimer.cancel()





if __name__=='__main__':
    HOST = '127.0.0.1'
    PORT_LOCAL = 11200
    PORT_LOWER = [11100]

    upper_addr = None
    local_addr = (HOST, PORT_LOCAL)
    lower_addr = [(HOST, i) for i in PORT_LOWER]  # 最多十个
    tst=NetModule(1,0 ,daemon=False)
    tst.start()
    tst.root.attributes('-alpha',1)
    print('')

