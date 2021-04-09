import threading
import socket
import tkinter as tk

import time
import random
import re
import json

'''
网络层协议如下：（暂定）
1字节     首定界符        F
1字节     确认帧          ACK  
1字节     负确认帧        NAK
1字节     链路层源地址    From
?字节     上层数据        DATA  包括编号 类型 设备号 数据本体 
1字节     循环冗余校验码  CRC   CRC-8 -> X8+ X2+ X+ 1
1字节     尾定界符        F
'''

class LnkModule(threading.Thread):
#----------------------------------------------下面是初始化函数——————————————————————————

    def __init__(self, Dev: int, Entity: int, Host: str = '127.0.0.1', cmd_addr=None, x=0, y=0, daemon=True,
                 filename='ne.txt',logger=None):
        super().__init__(daemon=daemon)

        self.Host=Host
        self.nefilename=filename
        self.up_addr = None  # 一般是没有上层端口的
        self.local_addr = (Host, 10200 + 1000 * Dev + Entity)
        self.Dev = Dev
        self.Entity = Entity
        self.cmd_addr = cmd_addr#控制地址 默认为空
        self.Layer='LNK'
        self.lower_addr = []  # 在这个网元模型中一个网元里只有一个网络层设备和一个应用层设备所以只拿了第一个

        self.winx=x
        self.winy=y
        self.routing = True

        self.buffer=[]#收到的信息缓存
        self.buff_send=[]#发送的信息的暂时缓存 格式（序号，发送的原文bytes）

        self.log_show= ''#消息栏展示的内容
        self.logger = logger

        self.txt1 = None

        self.addrlist=[(self.Dev,('127.0.0.1', 66666),time.time(),0)]#每个元素的格式：（目的设备号，下层地址，时间戳,跳数）
        self.history=[]#每个元素的格式：（某帧序号，时间戳）防止广播风暴的简单方法

        self.MaxRegetTime=20#当收到同一个帧两次的时候 会根据这个时间判断是否是重复产生的帧并删掉
        self.OutTimeAddr_DV=300
        self.OutTimeAddr_auto = 30
        self.Timer=[]#定时器列表 方便管理

        self.working=True

        self.send_num=0
        self.rcv_num=0
        self.break_num=0
        self.up_num=0


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
                            tmpupper = {0: None, 1: None, 2: None, 3: None, 4: None,
                                        5: None}  #初始化 避免串位置
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
                                if tmpupper[layer_no+1]!=None:
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
            #logging.warning("在匹配层次时出错")
            return 0

    def add_lower(self,addr):
        self.lower_addr.append(addr)
        if len(self.lower_addr)>1:
            self.routing=False#判断是否是路由器

    def add_up(self,addr):
        self.up_addr=addr
#---------------------------------------------关于地址表的部分-----------------------------------------------
    def addr_flesh(self):
        #根据当前的时间删除一些反向学习的内容
        nowtime=time.time()
        for i in self.addrlist:
            if i[0]==self.Dev:
                continue
            if nowtime-i[2]>=self.OutTimeAddr_DV or (nowtime-i[2]>=self.OutTimeAddr_auto and i[3]==-1 ):
                self.addrlist.remove(i)
        return True

    def addr_add(self,Dev,addr,jump=-1):#jump是从这个设备到另一个设备要经过多少个物理层。
        if Dev==self.Dev or Dev==255:
            return False
        self.addr_flesh()
        nowtime=time.time()
        rtn=False
        find=False
        self.logger.info("\t设备{}链路层试图增加这条记录：{}".format(self.Dev,[Dev,addr,jump]))

        for i in self.addrlist:
            if i[0]==Dev:               #如果有关于这个设备号的记录
                find=True
                if i[3]==-1:                 #记录是反向学习的
                    if jump ==-1:                #添加的记录是反向学习的
                                                    #仅仅更新时间 但是记录的端口号以老的为准
                        self.addrlist.remove(i)
                        self.addrlist.append((Dev, i[1], nowtime, -1))
                        #self.logger.info("{}".format(i))
                        self.logger.info("\t原纪录为反向学习 更新时间")
                        rtn= False
                    else:                       #添加的记录是动态路由算法的
                                                    #动态路由算法有更高优先权 记录动态路由算法的端口号
                        self.addrlist.remove(i)
                        self.addrlist.append((Dev, addr, nowtime, jump))
                        self.logger.info("\t原纪录为反向学习 更新DV路线")
                        rtn= True
                else:                       #记录是 动态路由算法学习 的(jump!=0)
                    if jump == -1:              #添加的是反向学习
                        if i[1]==addr and i[3]==jump:              #端口号一致且跳数一致
                            self.addrlist.remove(i)
                            self.addrlist.append((Dev, i[1], nowtime, jump))
                            self.logger.info("\t原纪录为反向学习 更新时间（确信度上升了）")
                        rtn=False                   #路由表没有实质上更改
                    elif i[1]==addr:              #记录的端口号和添加的端口号一样
                        if i[3]<=jump:              #记录的端口号跳数不大于添加的
                                                        #保留原来的 更新时间
                            self.addrlist.remove(i)
                            self.addrlist.append((Dev, i[1], nowtime, i[3]))
                            self.logger.info("\t原纪录为动态学习 保留原有")
                            rtn= False
                        else:                       #记录的端口号跳数大于添加的
                                                        #更新记录
                            self.addrlist.remove(i)
                            self.addrlist.append((Dev,addr,nowtime,jump))
                            self.logger.info("\t原纪录为动态学习 更新跳数")
                            rtn = True
                    else:                       #记录的端口号和添加的端口号不一致
                        if i[3]<=jump:              #记录的端口号跳数不大于添加的
                                                        #保留原来的，丢弃这条记录
                            self.logger.info("\t原纪录为动态学习 丢弃")
                            rtn = False
                        else:                       #记录的端口号跳数大于添加的
                                                        #更新记录
                            self.addrlist.remove(i)
                            self.addrlist.append((Dev,addr,nowtime,jump))
                            self.logger.info("\t原纪录为动态学习 更新记录")
                            rtn = False

        #如果压根没有关于这个设备的记录
        if find==False:
            self.addrlist.append((Dev,addr,nowtime, jump))#一个崭新的地址！
            self.logger.info("\t没有找到该端口的记录 直接添加")
            if jump==-1:
                rtn=False
            else:
                rtn=True

        self.logger.info("{}".format('\t更新了路由表' if rtn == True else '\t没更新路由表'))

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
        #查询是否有着历史记录 在时间限制之内（即判定为重复）则返回T 否则为F(未重复) 都会顺便更新时间
        nowtime = time.time()
        rtn = False
        for i in self.history:
            if i[0] == NO:
                if nowtime - i[1] <= self.MaxRegetTime:#若有重复的可能
                    rtn = True
                else:
                    rtn = False
                self.history.remove(i)
        self.history.append((NO, nowtime))
        return rtn


    def getNO(self):
        '''
        获得一个从未使用过的NO 包括接受历史 发送缓存两个部分
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
            for j in self.buff_send:
                if NO == j[0]:
                    i+=1
                    continue
            return NO
        return None

#----------------------------------------------网络层协议--------------------------------------------
    def Str012Bytes(self, s: str):
        '''
        ->bytes
        将字符串形式的01序列转化为Bytes形式（可以直接发送）
        :param s: 待转化字符串
        :return: 正常情况下为字符串对应的比特数组，否则为None
        '''
        if type(s) != str:
            return None
        msg = b''
        for i in range(0, len(s)):
            if s[i] == '0':
                msg = msg + b'\x00'
            elif s[i] == '1':
                msg = msg + b'\x01'
            else:
                return None
        return msg

    def Bytes2Str01(self, b: bytes):
        '''
        将Bytes形式的01序列转化为Str形式,不会对内容进行任何修改
        :param b: 待转化比特数组
        :return: 正常情况下为比特数组对应的字符串，否则为None
        '''
        if type(b) != bytes and type(b) != bytearray:
            return None
        msg = ''
        for i in range(0, len(b)):
            if b[i] == 0:
                msg = msg + '0'
            elif b[i] == 1:
                msg = msg + '1'
            else:
                print('error', b[i])
                return None

        return msg

    def protocol_encode(self,Data: bytes, ACK=False, NAK=False, No=65535, Type:str='00000001', DDev=None,SDev=None,From:int=None):
        '''
        输入Data为bytes类型的内容  返回的则是bytes类型的适应模拟器的可以发送的01比特数组
        From指该帧来自设备号几 方便确定NAK的目的地址（主） 以及确认邻居位置
        :return:
        '''
        if No>=65535:
            return None

        ack='11111111' if ACK else '00000000'
        nak='11111111' if NAK else '00000000'

        froms   = bin(From if From != None else self.Dev)[2:].rjust(8,'0')
        no      = bin(No)[2:].rjust(16,'0')
        types    = bin(int(Type,2))[2:].rjust(8,'0') if type(Type)==type(1) else Type


        ddev = '11111111' if DDev == None else bin(DDev)[2:].rjust(8, '0')
        sdev = bin(self.Dev if SDev == None else SDev )[2:].rjust(8, '0')


        data = self.Str01_encode(Data)

        crc = self.CRC_01(froms +no + types + ddev + sdev + data + '00000000')

        tmp = ack + nak + froms + no + types + ddev + sdev + data + crc

        rtn = ''
        count = 0
        for i in tmp:
            if i == '1':
                count += 1
                rtn += '1'
                if count == 5:
                    count = 0
                    rtn += '0'
            else:
                count = 0
                rtn += '0'

        rtn = '01111110' + rtn + '01111110'
        return self.Str012Bytes(rtn)

    def protocol_decode(self,Data: bytes):
        '''
        按照协议解码 返回字典 输入为byte 01字节组（从物理层直接收到的） NO是int
        :return: {'msg':str','NO':int,'ACK':bool,'NAK':bool,......}
        '''
        s=self.Bytes2Str01(Data)
        rtn = {}
        x = len(re.findall(r'01111110', s))
        if  x != 2:
            self.logger.debug('设备{}链路层 找到{}个定界符01111110'.format(self.Dev,x))
            cut=re.split(r'01111110', s)
            bol=None
            for i in cut[1:-1]:
                try:
                    bol=self.protocol_decode(self.Str012Bytes('01111110'+i+'01111110'))
                    assert  bol['flag']==True
                except:
                    pass
            if bol==None:
                self.logger.error('设备{}链路层 找到{}个定界符01111110 且每一段分割都不能正确解析'.format(self.Dev,x))
                raise Exception('设备{}链路层 找到{}个定界符01111110 且每一段分割都不能正确解析'.format(self.Dev,x))
            else:
                return bol
            #raise ValueError('找到{}个定界符01111110'.format(x))


        cut = re.split(r'01111110', s)
        txt = cut[1]
        # 只处理只有两个的 别的超时重传解决
        # 这里的选择方案比较随意
        msg = ''#解除按位插入后的信息
        count = 0
        for i in txt:
            if count == 5:
                count = 0
                continue
            if i == '1':
                count += 1
                msg += '1'
            if i == '0':
                count = 0
                msg += '0'


        ack = True if msg[ 0: 8].count('1') > 4 else False
        nak = True if msg[ 8:16].count('1') > 4 else False

        From  = int(msg[16:24], 2)
        no    = int(msg[24:40], 2)
        types = msg[40:48]
        ddev  = int(msg[48:56],2)
        sdev  = int(msg[56:64],2)
        #echo = True48 if msg[24:28].count('1') > 2 else False
        data = msg[64:-8]
        # if len(data)%8!=0:
        #     print(data)
        crc  = msg[-8:]

        rtn[ 'ACK'] = ack
        rtn[ 'NAK'] = nak
        rtn['From'] = From

        rtn[ 'NO' ] = no
        rtn['Type'] = types
        rtn['DDev'] = ddev
        rtn['SDev'] = sdev
        rtn['Data'] = data

        rtn[ 'CRC'] = crc
        z = self.CRC_check(msg[16:])#在解码的时候就顺便crc检测
        if  z != True:#检测结果放在flag中
            self.logger.info('设备{}链路层接收到的No.{} data的CRC校验未通过:'.format(self.Dev,no)+z)
            rtn['flag'] = z
        else:
            rtn['flag'] = True
        return rtn

    def Str01_decode(self,s: str):
        '''
        将01字符串（不加任何标识符和纠错码）转化为对应的bytes类型
        :param s:01字符串
        :return:解码原文
        '''
        if len(s) == 0:
            return b''
        if len(s) % 8 != 0:
            raise Exception('编码不是八的倍数')
        msg = re.sub(r'0x', '', hex(int(s, 2)))
        rtn = bytes.fromhex(msg)
        return rtn

    def Str01_encode(self, Data: bytes):
        '''
        将字节类型的Data转化为01字符串
        :return: 字符串对应01字符串
        '''
        bc = [bin(int(i))[2:].rjust(8, '0') for i in Data]
        rtn = ''.join(bc)
        return rtn

    def CRC(self,line_:str):
        '''
        接受16进制str输入，输出CRC校验和（int)
        :return:crc:int
        '''
        line_ = bin(int('f' + line_, 16))[6:]
        reg = 0
        for bit in line_:
            if reg & 0x80 != 0:
                reg <<= 1
                reg &= 0xff
                if bit == '1':
                    reg += 1
                    reg &= 0xff
                reg ^= 0x07
            else:
                reg <<= 1
                reg &= 0xff
                if bit == '1':
                    reg += 1
                    reg &= 0xff
        return reg & 0xff

    def CRC_01(self,s01:str):
        rtnint=self.CRC(hex(int(s01,2))[2:])
        return bin(rtnint)[2:].rjust(8,'0')

    def CRC_check(self,s:str,mod='1000000111'):
        '''
        :param s: 待验证的01字符串码
        :param mod: 默认CRC-8
        :return: 处理后的码是否符合标准
        '''
        x=self.CRC_01(s)
        rtn=True
        if x !='00000000':
            rtn = x
        return rtn

#----------------------------------------------发送函数--------------------------------------------
    def send2up(self, Data:bytes= b'', Type:str= '00000001', DDev=None, SDev=None, No=None):
        '''
        不指定No认为是交换机的链路层  向上发送给应用层。否则认为是路由器 向上发送给网络层
        :return:
        '''
        self.sendtocmd('s')
        if self.socket == None:
            self.logger_add('没有绑定套接字端口，发送失败')
        if self.up_addr==None:
            self.logger.debug('设备{}链路层 上传失败 原因是没有上层地址'.format(self.Dev))
            return False
        if SDev==None:
            SDev=self.Dev


        rtn = b''
        self.logger.debug('设备{}链路层 正在上传收到的内容'.format(self.Dev))
        #self.logger.debug('设备{}链路层 试图发送的类型为：Type{} DDev{} SDev{} No{}'.format(self.Dev,Type,DDev,SDev,No))
        if No != None:#根据上层协议的不同来控制发送的内容 缺省的时候是发送给APP 否则是给NETNET
            no=hex(No)[2:].rjust(4, '0')
            rtn+=bytes.fromhex(no)
            #self.logger.debug('设备{}链路层 No完成'.format(self.Dev))

        type = hex(int(Type,2))[2:].rjust(2, '0')
        rtn += bytes.fromhex(type)
        #self.logger.debug('设备{}链路层 Type完成'.format(self.Dev))

        if DDev != None:
            ddev = hex(int(DDev))[2:].rjust(2, '0')
        else:
            ddev = 'ff'
        rtn += bytes.fromhex(ddev)
        #self.logger.debug('设备{}链路层 DDev完成'.format(self.Dev))

        sdev = hex(int(SDev))[2:].rjust(2, '0')
        rtn += bytes.fromhex(sdev)
        #self.logger.debug('设备{}链路层 SDev完成'.format(self.Dev))

        rtn += Data

        msgsend=rtn

        self.socket.sendto(msgsend, self.up_addr)#毫无疑问的只有一个上层
        self.up_num += 1
        self.lb_up.configure(text='累交：{}'.format(self.up_num))
        self.sendtocmd('n')
        return True

    def main_send(self,Data:bytes=b'',ACK=False,NAK=False,NO=0,Type:str='00000001',DDev=None,SDev=None):
        '''
        传入的st是明文
        '''
        if self.socket == None:
            self.logger_add('没有绑定套接字端口，发送失败')
        if DDev==self.Dev:
            self.logger.info('设备{}链路层试图向下发送到自己的设备中，请求被拒绝了'.format(self.Dev))
        #先对明文进行转化然后用protocol编写出来 此时的msgsend是bytes类型的01字节组
        msgsend=self.protocol_encode(Data,ACK,NAK,NO,Type,DDev,SDev)


        if Type[-1]!='1' and DDev!=255:#单播 type！=1且目的地址非空
            x=self.addr_find(DDev)
            if x != None:
                self.send2low(msgsend,[x],NO)
                self.logger_add('单播帧 序号{},地址{}'.format(NO, x))
                self.logger.info('设备{}链路层 单播序号{}成功，端口号为{}'.format(self.Dev,NO,x[1]))
            else :
                self.logger_add('单播帧 序号{} 地址表中没有信息，认为不可达，丢弃'.format(NO, self.lower_addr))
                self.logger.info('设备{}链路层 单播序号{}，地址表中未找到信息，丢弃'.format(self.Dev,NO))
        else:
            self.send2low( msgsend, self.lower_addr, NO, retran=False)#真广播 不要重传
            self.logger_add('广播帧 序号{} 地址{}'.format(NO, self.lower_addr))
            self.logger.info('设备{}链路层 广播序号{}，地址表中未找到信息，丢弃'.format(self.Dev, NO))
        return True

    def send2low(self,Data:bytes,addr:list,NO:int,retran=True,pause=3,count=0, history_add=True):
        '''
        NO必须是int,Data这里是可以直接发送的byte类型 函数自带一步检错NO对应
        '''
        if count==0:
            try:
                dicsend=self.protocol_decode(Data)
                if dicsend['NO']!=NO:
                    raise Exception('发送帧不能正确解析')
                if dicsend['flag']!=True:
                    raise Exception("CRC校验失败：{}".format(dicsend['flag']))
            except Exception as z:
                self.logger.exception("设备{}发送的序号为{}的帧,解析失败 Error:{}".format(self.Dev,NO,z))
                return False

        self.sendtocmd('s')
        self.Timer_cancel(NO)
        if history_add:
            self.history_add(NO)  # 自己发送的帧有可能以一般帧的形式传回来给自己 需要拒绝掉
        self.buff_send.append((NO, Data))

        if count>5:
            self.logger_add('重发次数超过五，放弃重传'.format(NO, count))
            self.clearbufsend(NO)
            return False
        if count !=0:
            self.logger_add('重发了序号为{}的帧,第{}次'.format(NO,count))
            self.logger.debug('本次发送为重发')
        No=NO-1
        for i in addr:
            No+=1
            self.socket.sendto(Data,i)
            self.send_num += 1
            self.lb_send.configure(text='累发：{}'.format(self.send_num))

            self.logger.debug("※链路层设备{}向地址{}发送了数据".format(self.Dev,i))
            if retran:
                timertmp = threading.Timer(pause, self.send2low, ( Data, [i], NO, True, pause ,count + 1))
                self.Timer.append({'timer': timertmp, 'No': NO})
                timertmp.start()
                #相关的计时器要在确认帧到达时关闭
        self.sendtocmd('n')
        return True


    def Timer_cancel(self,NO):
        for i in self.Timer:
            if NO == i['No']:#所有序号合适的始终都会删除 所以可以广播
                i['timer'].cancel()
                self.Timer.remove(i)

    def getbufsend(self,NO):
        '''获得对应序号在发送缓存中的内容->Byte'''
        for i in self.buff_send:
            if NO == i[0]:
                return i[1]
        return None

    def clearbufsend(self,NO,pause=60):
        if pause==0:
            for i in self.buff_send:
                if NO == i[0]:
                    self.buff_send.remove(i)
                    return True
        else:
            timer = threading.Timer(pause,self.clearbufsend,(NO,0))
            timer.start()
        return False

#----------------------------------------------接收函数※——————————————————————————
    #实际上所有发送都是在接收的基础上发生的 所以这边的函数可能会比较的复杂

    def main_recv(self,data:bytes,addr):
        #调用这个函数将会从缓存区获得一个报文 并进行适当的处理
        if addr==self.up_addr and self.routing == False:#交换机默认上层是APP层
            Type = bin(data[0])[2:].rjust(8,'0')
            DDev = data[1]
            SDev = data[2]
            Data_str = data[3:]#来自上层 则能直接转化为明文文本
            self.logger.debug('交换机设备{}链路层从上层获得了帧'.format(self.Dev))
            if SDev==DDev:
                self.send2up(Data_str,Type,DDev,SDev)
                self.logger_add('从上层端口{}获得了帧，发送给本设备，回传'.format(addr))

            elif int(Type,2)%2==1 or DDev==255:#(\xff
                No = self.getNO()
                self.logger_add('从上层端口{}获得了帧，尝试广播,帧序号为{}'.format(addr, No))
                self.main_send( Data_str, ACK=False, NAK=False, NO=No, Type=Type, DDev=DDev, SDev=SDev)


            else:
                No = self.getNO()
                self.logger_add('从上层端口{}获得了帧，试图单播设备{},帧序号为{}'.format(addr, DDev, No))
                self.main_send( Data_str, ACK=False, NAK=False, NO=No, Type=Type, DDev=DDev, SDev=SDev)
        elif addr==self.up_addr and self.routing == True:
            No   = data[0]*256+data[1]
            Type = bin(data[2])[2:].rjust(8,'0')
            DDev = data[3]
            SDev = data[4]
            Data_str = data[5:]
            self.logger.debug('路由器 设备{}链路层从上层获得了帧,序号{}'.format(self.Dev,No))
            if  Type[0:4].count('1') > 2 :#动态路由算法 收到
                self.logger.debug('设备{}链路层 收到的是"动态路由算法"广播帧'.format(self.Dev))

                self.rcv_DV(Data_str,addr,jumpadd=0)#是同一个设备内部的情况 则不需要加一跳

                self.send_DV([addr])

                self.logger_add('序{} 源{} 目{}，从端口{}发送了DV一般帧 '.format(No, SDev, DDev, addr))

            elif DDev==self.Dev:
                self.send2up(Data_str, Type, DDev, SDev,No)
                self.logger_add('从上层端口{}获得了帧，发送给本设备，上传'.format(addr))
            elif int(Type,2)%2==1 or DDev==255:
                self.logger_add('从上层端口{}获得了帧，尝试向下广播,帧序号为{}'.format(addr, No))
                self.main_send( Data_str, ACK=False, NAK=False, NO=No, Type=Type, DDev=DDev, SDev=SDev)
            else:
                self.logger_add('从上层端口{}获得了帧，试图单播设备{},帧序号为{}'.format(addr, DDev, No))
                self.main_send( Data_str, ACK=False, NAK=False, NO=No, Type=Type, DDev=DDev, SDev=SDev)


        elif addr in self.lower_addr: #来自下层 物理层
            self.logger.debug('设备{}链路层从下层端口{}获得了帧'.format(self.Dev,addr[1]))
            try:#尝试解析帧
                msgdic=self.protocol_decode(data)
                assert len(msgdic)>0
            except Exception as z:
                self.logger.info('链路层设备{}实体{}解析下层帧失败，Error:{}'.format(self.Dev,self.Entity,z))
                self.logger_add('从端口{}获得了帧，无法解析,丢弃 错误：{}'.format(addr,z))
                self.break_num += 1
                self.lb_break.configure(text='累弃：{}'.format(self.break_num))
                return True

            self.logger.debug('设备{}链路层获得帧 定位完成'.format(self.Dev))
            #对字典进行拆分
            Type = msgdic['Type'];  DDev = msgdic['DDev'];  SDev = msgdic['SDev']
            NO = msgdic['NO'];      ACK = msgdic['ACK'];    NAK = msgdic['NAK']
            Data_str = msgdic['Data']; CRC = msgdic['CRC'] ;    From = msgdic['From']
            try:
                Data_bytes = self.Str01_decode(Data_str)
                assert not ACK or not NAK
                if msgdic['flag'] != True:
                    raise Exception('CRC校验错误{}'.format(msgdic['flag']))
            except Exception as z:
                self.logger.info('链路层设备{}实体{}解析下层帧失败，发送NAK，Error:\n{}'.format(self.Dev, self.Entity, z))
                self.logger.debug('设备{}链路层 解析失败 ※发送NAK'.format(self.Dev))
                nak = self.protocol_encode(b'', NAK=True, Type=Type, DDev=From, SDev=SDev, No=NO)
                self.history = [i for i in self.history if i[0]!=NO]


                self.send2low(nak, [addr], NO, retran=False,history_add=False)
                self.break_num += 1
                self.lb_break.configure(text='累弃：{}'.format(self.break_num))
                return True

            self.logger.debug('设备{}链路层获得帧 通过了校验 序号为{}'.format(self.Dev,NO))
            #检测重复性：
            if ACK == False and NAK == False:#只检测一般帧的重复 确认帧不检测(确认帧的序号和发送的帧的序号是一样的）
                if  self.history_check(NO):#未来得及停下的已经发送的帧 没有收到确认帧而重发的帧 因为NAK重发的帧 绕了一圈回来的帧
                    self.logger_add('从端口{}获得了帧，序号为{}，判断为重复'.format(addr,NO))
                    self.logger.debug('判断为重复帧，丢弃')
                    self.break_num += 1
                    self.lb_break.configure(text='累弃：{}'.format(self.break_num))
                    if DDev==self.Dev:
                        ack = self.protocol_encode(b'', ACK=True, Type='00000000', DDev=SDev, SDev=self.Dev, No=NO)
                        self.send2low(ack, [addr], NO, retran=False)
                        self.logger_add('因为重复帧，发送了确认帧'.format(addr, NO))
                        self.logger.debug('该帧目的地址是自己，试图重发一个确认帧来阻止重发')
                    return True #重复帧安全性未可知（比如成环） 不进行学习 直接丢掉


            # 反向地址学习： 当判断该帧来自自己的下层端口时 会到这一步
            self.addr_add(SDev,addr)


            if  Type[0:4].count('1') > 2 :#动态路由算法 收到
                self.logger.debug('设备{}链路层 收到的是动态路由算法广播帧'.format(self.Dev))
                if ACK:
                    self.logger.debug('设备{}链路层 收到了一个DV ACK帧 但是这不应该发生 丢弃'.format(self.Dev))

                elif NAK:
                    if DDev==self.Dev:
                        self.logger.debug('设备{}链路层 是本设备的DV NAK帧'.format(self.Dev))
                        self.logger_add('序{} 源{} 目{}，从端口{}获得了DV NAK帧，重发路由表 来自设备{}'.format(NO,SDev,DDev,addr, From ))

                        self.send_DV([i for i in self.lower_addr if i != addr])#只给addr对应的下层传送这个路由表 其它的都排除掉
                        self.logger.debug('已经重发路由表')
                    else:
                        self.logger.debug('设备{}链路层 不是本设备的DV NAK帧 丢弃'.format(self.Dev))
                else:
                    if self.rcv_DV(Data_bytes,addr):
                        self.send_DV([addr])

                    self.send2up(Data_bytes,'11110001', DDev, SDev, NO)
                    self.history_add(NO)  # 完美收到的帧 不期待重复的帧 记录到历史中
                    self.logger_add('序{} 源{} 目{}，从端口{}获得了普通DV帧，学习后上传 来自设备{}'.format(NO, SDev, DDev, addr, From))

            elif self.routing or DDev==self.Dev:
                self.logger.debug('设备{}链路层 {}'.format(self.Dev,'进入路由器工作模式' if self.routing else '收到了目的地址为自己的帧'))
                if ACK:
                    self.logger.debug('设备{}链路层 收到了一个ACK帧'.format(self.Dev))
                    if DDev == self.Dev:
                        self.logger.debug('是本设备的ACK帧'.format(self.Dev))
                        self.logger_add('序{} 源{} 目{}，从端口{}获得了ACK帧，不再转发 来自设备{}'.format(NO, SDev, DDev, addr,From))
                        self.Timer_cancel(NO)  # 帧已经收到 相同序号的重发记时停止
                        self.clearbufsend(NO)  # 一段时间后，清空对应序号的重发缓存
                    else:
                        self.logger.debug('不是本设备的ACK帧 弃'.format(self.Dev))
                        self.break_num += 1
                        self.lb_break.configure(text='累弃：{}'.format(self.break_num))
                elif NAK:
                    self.logger.debug('设备{}链路层 收到了一个NAK帧'.format(self.Dev))
                    if DDev == self.Dev:
                        self.logger.debug('是本设备的NAK帧'.format(self.Dev))#负确认帧触发的重传不会超时重传 也不会删除原有的重传计时器
                        self.logger_add('序{} 源{} 目{}，从端口{}获得了NAK帧试图重发 来自设备{}'.format(NO, SDev, DDev, addr, From))
                        resend=self.getbufsend(NO)
                        if resend == None:
                            self.logger.error('缓存区不存在序号为{}的帧,无法实现重发'.format(NO))
                        else:
                            self.send2low(resend,[addr],NO,retran=False)
                            self.logger.debug('NAK请求的对应帧已经重发'.format(NO))

                    else:
                        self.logger.debug('不是本设备的NAK帧 弃'.format(self.Dev))
                        self.break_num += 1
                        self.lb_break.configure(text='累弃：{}'.format(self.break_num))
                else:
                    self.logger.debug('设备{}链路层 收到的是一般帧'.format(self.Dev))
                    ack = self.protocol_encode(b'', ACK=True, Type='00000000', DDev=From, SDev=self.Dev, No=NO)

                    self.send2low(ack, [addr], NO, retran=False)
                    self.logger.debug('设备{}链路层 发送了确认帧'.format(self.Dev))

                    if self.send2up( Data_bytes, Type, DDev, SDev, NO):
                        self.logger.debug('设备{}链路层 上传了该帧'.format(self.Dev))

                    self.history_add(NO)  # 完美收到的帧 不期待重复的帧 记录到历史中
                    self.logger_add('序{} 源{} 目{}，从端口{}获得了普通帧，上传,回复确认帧 来自设备{}'.format(NO, SDev, DDev, addr,From))
            else:#当目的地址不是自己的时候 转发 转发不重传不期待回复 要重传也是源来做 但是解析出错的时候可以冒充目的地址发送NAK帧

                self.logger.debug('设备{}链路层 进入交换机转发工作模式'.format(self.Dev))

                Daddr=self.addr_find(DDev)
                if Daddr==addr:
                    self.logger_add('序{} 源{} 目{}，从端口{}获得了帧,试图发送给接受地址 拒绝'.format(NO, SDev, DDev, addr, From))
                    self.logger.debug('设备{}链路层 试图发送给接受地址 拒绝'.format(self.Dev))
                    self.break_num += 1
                    self.lb_break.configure(text='累弃：{}'.format(self.break_num))
                    return True
                sendmsg=self.protocol_encode(Data_bytes,No=NO,Type=Type,DDev=DDev,SDev=SDev)

                if Daddr == None:
                    addrs=[i for i in self.lower_addr if i != addr]
                    self.send2low(sendmsg,addrs,NO,retran=False)
                    self.logger_add('序{} 源{} 目{}，从端口{}获得了帧，泛洪转发到端口{} 来自设备{}'.format(NO,SDev,DDev,addr,addrs,From ))
                    self.logger.debug('设备{}链路层 泛洪转发了一些帧'.format(self.Dev))

                else:
                    self.send2low(sendmsg,[Daddr],NO,retran=False)
                    self.logger_add('序{} 源{} 目{}，从端口{}获得了帧，单播转发到端口{} 来自设备{}'.format(NO,SDev,DDev,addr ,Daddr,  From))
                    self.logger.debug('设备{}链路层 单播转发了一个帧'.format(self.Dev))

        else:
            self.logger_add('从端口{}获得了帧，来源未知，丢弃，不记录'.format(addr))
            self.logger.debug('设备{}链路层 收到的是来源未知的帧'.format(self.Dev))
            self.break_num += 1
            self.lb_break.configure(text='累弃：{}'.format(self.break_num))

        return True

    def rcv_FromSocket_loop(self, f=0.1):
        '''
        开始尝试从套接字接受内容，接收到的消息会原封不动的保存self.buff中，用其他函数来提取。
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
                return
            else:
                self.handle_cmd(data)
        else:
            self.buffer.append(tmp)
            self.Lab_buff.configure(text='buff:{}'.format(len(self.buffer)))
        return

    def rcv_FromBuff_loop(self, f=0.20, *args):
        '''
        每隔一段时间调用一次main_recv函数 在内部判断是否有调用条件 受到self.working影响
        这个函数一直在重复的被调用 不会停止 所以提取频率的控制可能是需要注意的
        '''
        timer = threading.Timer(f, self.rcv_FromBuff_loop, (f,))

        if self.working:
            if len(self.buffer)!=0:
                #print('缓存非空，尝试处理')
                rtn = self.buffer.pop(0)
                timer.start()
                try:
                    self.logger.debug('- - - - -设备{}链路层   开始处理帧  - - - - -'.format(self.Dev))
                    self.sendtocmd('r')
                    self.main_recv(*rtn)
                    self.sendtocmd('n')
                    self.logger.debug('- - - - -设备{}链路层 处理完了一个帧- - - - -\n'.format(self.Dev))
                except Exception as error:#如果main_recv在运行过程中挂掉了 那么就要在这里手动重启一下rsv_start函数
                    self.logger.error('设备{}接受失败：{}'.format(self.Dev,error))

                self.Lab_buff.configure(text="buff:{}".format(len(self.buffer)))
                self.rcv_num += 1
                self.lb_rcv.configure(text='累收：{}'.format(self.rcv_num))
            else:
                timer.start()
        return


#----------------------------------------------可视化界面函数——————————————————————————
    def logger_add(self,*args,end='\n'):
        for i in args:
            self.log_show+= i + end
        self.txt1.delete('1.0','end')
        self.txt1.insert(tk.END, self.log_show)
    def logger_clear(self):
        self.log_show= ''
        self.txt1.delete('1.0', 'end')
        self.rcv_num=0
        self.break_num=0
        self.up_num=0
        self.send_num=0

        self.lb_rcv.configure(text='累收：{}'.format(self.break_num))
        self.lb_break.configure(text='累弃：{}'.format(self.break_num))
        self.lb_up.configure(text='累交：{}'.format(self.break_num))
        self.lb_send.configure(text='累发：{}'.format(self.break_num))

    def newinfo(self,root):
        # global root
        winNew = tk.Toplevel(root)
        winNew.geometry('300x125')
        self.addr_flesh()
        winNew.title('地址表信息')
        temptxt =   '       端口号       目的地址  时间 跳数\n'
        #temptxt += '("127.0.0.1",11200)    1      30\n'
        self.addr_flesh()
        if len(self.addrlist)!=0:
            for i in self.addrlist:
                temptxt+='{}   {:}       {}s  {}\n'.format(i[1],i[0],int(time.time()-i[2]),i[3])
        self.txtinfo=tk.Text(winNew)
        self.txtinfo.delete('1.0','end')
        self.txtinfo.insert(tk.END,temptxt)
        self.txtinfo.place(relx=0, rely=0, relheight=1, relwidth=1)

    def newroot(self, funcPause=None,x=0,y=0):
        '''
        配置一个窗口 并且将窗口对应的按钮绑定好
        绑定方法：没有参数直接写函数名 有参数使用lambda函数 lambda:func(xxx)
        窗口的大部分内容都不能自定义（简介起见）
        可以通过对四个函数的合理搭配来取代传统的case方法
        要运行这个窗口 请使用root.mainloop() #root是该函数的返回值
        :param funcPause:四个按钮对应的函数
        :return: 这个窗口本身root
        '''
        root = tk.Tk()
        root.title('设备{}链路层实体{}界面'.format(self.Dev, self.Entity))
        root.attributes("-alpha", 0)
        root.geometry('300x300+{}+{}'.format(x,y))  # 这里的乘号不是 * ，而是小写英文字母 x

        frm1 = tk.Frame(root)
        frm1.place(relx=0, rely=0, relheight=1, relwidth=1, height=-120)

        lb1 = tk.Label(frm1, text='消息', fg='black', font=("黑体", 9), anchor=tk.W)
        lb1.place(relx=0, rely=0, height=30, relwidth=0.25)

        self.Lab_buff = tk.Label(frm1, text='buff:0', relief=tk.GROOVE)
        self.Lab_buff.place(relx=0.6, rely=0, height=30, relwidth=0.2)

        btninfo = tk.Button(frm1, text='地址表', relief=tk.GROOVE, command=lambda: self.newinfo(root))  #
        btninfo.place(relx=0.8, rely=0, height=30, relwidth=0.2)

        self.txt1 = tk.Text(frm1)
        self.txt1.place(relx=0, rely=0, y=30, relheight=1, height=-20, relwidth=1)

        # relief=tk.GROOVE
        frminfo = tk.Frame(root)
        frminfo.place(relx=0, rely=1, height=40, relwidth=1, y=-120)
        lbinfo = tk.Label(frminfo, text='上层地址：{}\n本地地址：{}\n下层地址：{}'.format(self.up_addr, self.local_addr, self.lower_addr) ,
                          fg='black', font=("黑体", 9), relief=tk.GROOVE)
        lbinfo.place(relx=0, rely=0, relheight=1, relwidth=1)

        frm = tk.Frame(root)
        frm.place(relx=0, rely=1, height=80, relwidth=1, y=-80)


        lb2 = tk.Label(frm, text='控制台：', fg='black', font=("黑体", 9), anchor=tk.CENTER)
        lb2.place(relx=0, rely=0, relheight=0.3, relwidth=0.3)

        self.btn1 = tk.Button(frm, text='暂停', command=funcPause)
        self.btn1.place(relx=0,rely=0.3,relheight=0.3,relwidth=0.3)
        btn2 = tk.Button(frm, text='刷屏', command=self.logger_clear)
        btn2.place(relx=0, rely=0.62, relheight=0.3, relwidth=0.3)

        lb3 = tk.Label(frm, text='统计', fg='black', font=("黑体", 9), anchor=tk.W)
        lb3.place(relx=0.4,rely=0,relheight=0.2,relwidth=0.5)

        self.lb_send = tk.Label(frm, text='累发：{}'.format(self.send_num), fg='black', font=("黑体", 9), anchor=tk.W, relief=tk.GROOVE)
        self.lb_send.place(relx=0.4, rely=0.25, relheight=0.3, relwidth=0.3)

        self.lb_rcv = tk.Label(frm, text='累收：{}'.format(self.rcv_num), fg='black', font=("黑体", 9), anchor=tk.W, relief=tk.GROOVE)
        self.lb_rcv.place(relx=0.4, rely=0.55, relheight=0.3, relwidth=0.3)

        self.lb_up = tk.Label(frm, text='累交：{}'.format(self.up_num), fg='black', font=("黑体", 9), anchor=tk.W, relief=tk.GROOVE)
        self.lb_up.place(relx=0.7, rely=0.25, relheight=0.3, relwidth=0.3)

        self.lb_break = tk.Label(frm, text='累弃：{}'.format(self.break_num), fg='black', font=("黑体", 9), anchor=tk.W, relief=tk.GROOVE)
        self.lb_break.place(relx=0.7, rely=0.55, relheight=0.3, relwidth=0.3)
        return root

    def button_switch(self):
        self.working=not self.working
        self.btn1.configure(text='暂停'if self.working else '开始')
        if self.working :
            self.rcv_FromBuff_loop()
        return

    def sendtocmd(self,color):
        tmp=''
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
#----------------------------------------------动态路由----------------------------------------------
    def rcv_DV(self,Data,addr,jumpadd=1):#要传入源地址的
        self.logger_add('从端口{}接收到了路由表'.format(addr))
        self.logger.debug("设备{}链路层DV 收到的内容为{}".format(self.Dev,Data))
        addrstr=Data.decode()
        addrload=json.loads(addrstr)
        rtn=False
        Dv_num=0
        for i in addrload:
            self.logger.debug("正在处理{}".format(i))
            jump=i["jump"]+jumpadd    #若选择这条路 自己的跳数会在原来的基础上+1
            DDev=i['DDev']
            if jump<=0:#过滤反向地址学习的部分
                continue
            else:
                Dv_num+=1
                tmp=self.addr_add(DDev,addr,jump)#大多数情况都能在addr_add中解决 除了jump=0不能直接取分
                rtn=tmp or rtn
        if Dv_num<=len([i for i in self.addrlist if i[3]!=-1 ]):
            rtn=True
        return rtn#决定是否下发自己的路由表

    def send_DV(self,exceptaddr:list=None):
        self.logger_add('正在向除了{}的邻居转发自己的路由表'.format(exceptaddr))
        self.logger.info('***正在向除了{}的邻居转发自己的路由表'.format(exceptaddr))
        #self.logger.debug('路由表：{}'.format(self.addrlist))
        if exceptaddr == None:
            exceptaddr=[]
        formatjson=[]
        for i in self.addrlist:
            #self.logger.debug('{}'.format(i))
            l = {'DDev': i[0], 'jump': i[3]}
            formatjson.append(l)
        #if len(formatjson)==0:
        #    return False
        addrstr=json.dumps(formatjson)
        Datasend=addrstr.encode()

        self.logger.info('设备{} 路由表发送内容{}'.format(self.Dev, addrstr))
        No = self.getNO()
        msgsend=self.protocol_encode(Datasend,Type="11110001",No=No)
        for i in self.lower_addr:
            if i not in exceptaddr:
                self.send2low(msgsend,[i],No,retran=False)
                self.logger_add('向{}转发自己的路由表'.format(i))
                self.logger.info('向{}转发自己的路由表'.format(i))
        self.logger_add('转发完毕'.format(exceptaddr))
        self.logger.info('转发完毕'.format(exceptaddr))
                #self.socket.sendto(msgsend,i)
        return True
#----------------------------------------------主函数——————————————————————————

    def run(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.bind(self.local_addr)
            s.setblocking(False)
            self.read_ne(self.nefilename)
            self.socket=s

            #s.setblocking(False)
            self.rcv_FromSocket_loop(0.1)
            self.root = self.newroot(funcPause=self.button_switch,x=self.winx,y=self.winy)
            #self.logger_add('当前处于网络层 设备号：{}'.format(self.Dev))
            self.rcv_FromBuff_loop(f=0.1)

            self.root.mainloop()
            self.rcvtimer.cancel()
            self.working=False
            #print('设备号 {} 实体号{} 链路层停止工作'.format(self.Dev,self.Entity))

if __name__=='__main__':
    HOST = '127.0.0.1'
    PORT_LOCAL = 11200
    PORT_LOWER = [11100]

    upper_addr = None
    local_addr = (HOST, PORT_LOCAL)
    lower_addr = [(HOST, i) for i in PORT_LOWER]  # 最多十个
    tst=LnkModule(2,2,daemon=False)
    tst.start()
    tst.root.attributes('-alpha',1)
    print('')