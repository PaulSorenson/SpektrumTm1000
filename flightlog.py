#

'''
TLM file decoder.  This is the format the DX18 flight logs are stored in.

Builds on information gleened from RC enthusiasts on the web eg,
see: http://www.rcgroups.com/forums/showthread.php?t=1725173

.. moduleauthor:: paul sorenson
'''


import sys
from argparse import ArgumentParser
import datetime
import os, os.path
import glob
import shutil
from ctypes import *


blocktypes = {
    #0x3: 'current',
    0x17: 'speed',
    0x18: 'altitude',
    0x7e: 'RPM-Volt-Temp',
    0x7f: 'Rxdata',
}
'''
Blocktypes are determined by the first byte after the ffff ffff.
ie BlockDataType.t1.
'''


class BlockTag(Structure):
    '''
    Start of each block is either ffff ffff or
    time stamp.

    This does not seem to be BigEndian which doesn't jibe with
    the other fields.
    '''

    _fields_ = [('tag', c_uint)]

    TAG = 0xffffffff


    def isdata(self):
        return self.tag != self.TAG


    def value(self):
        return self.tag


    @property
    def timestamp(self):
        if self.tag == 0xffffffff:
            raise Exception('Not a timestamped block')
        else:
            return self.tag/100.0


    def __str__(self):
        return str(self.timestamp) if self.isdata() else "0"


class BlockDataType(Structure):
    '''
    Two bytes that follow date (or ffff ffff).
    '''

    _fields_ = [
            ('t1', c_byte),     # byte 5
            ('t2', c_byte),     # byte 6
        ]
    '''
    See blocktypes for definitions of t1.  I think the very first
    block of the file is an exception to these rules.

    If t1 == t2 then this block is header data (only follows FFFF FFFF?).

    If t2 == 0 then it is name(?) info (only follows timestamp?).

    It t2 != 0 and t1 != t2 then assume this is header for a new 
    flight log.

    .. note:: Not sure if that assumption holds, t1 and t2 might be
        model number model type which I can't be sure are always non-zero.
    '''


    @property
    def value(self):
        return (self.t1, self.t2)


    @property
    def description(self):
        dt = blocktypes.get(self.t1, 'unknown({0})'.format(hex(self.t1)))

        if self.t2 == 0:
            rt = 'data'
        elif self.t1 == self.t2:
            rt = 'header'
        else:
            rt = 'header'
            dt = 'flight start'

        return (rt, dt)


    def __str__(self):
        return '{0} {1}'.format(*self.description)
 

class FlightLogHeader(Structure):
    '''
    First block of each data capture.
    '''

    _fields_ = [
            ('header_pre', c_byte * 6),     # @todo
            ('header', c_byte * 20),
            ('header_post', c_byte * 4),    # @todo
        ]


    def getheader(self):
        '''Get the text of the header.'''
        return string_at(self.header)

        
    def __str__(self):
        return '{0}'.format(self.getheader())


    def asdict(self):
        return {'model name': self.getheader()}


class TLMDataHdr(Structure):

    _fields_ = [
            ('data', c_byte * 30),
        ]


    def __str__(self):
        return ' '.join([hex(i) for i in self.data])


    def asdict(self):
        return {'data': str(self)}


class TLMData(BigEndianStructure):

    _fields_ = [
            ('data', c_ushort * 7),
        ]


    def __str__(self):
        return ' '.join([hex(i) for i in self.data])


    def asdict(self):
        return {'data': self.data}


class TLMRpmVoltData(BigEndianStructure):

    _fields_ = [
            ('RPM', c_ushort),
            ('Volt', c_ushort),
            ('TempF', c_ushort),
            ('data', c_ushort * 4),
        ]


    @property
    def TempC(self):
        return (self.TempF - 32) * 5 / 9


    blockdatatype = 0x7e


    def asdict(self):
        return {
            'RPM': self.RPM,
            'Volt': self.Volt/100.0,
            'TempC': self.TempC/100.0,
            # 'data': data,
        }
        

class TLMRxData(BigEndianStructure):

    _fields_ = [
            ('A', c_ushort),
            ('B', c_ushort),
            ('L', c_ushort),
            ('R', c_ushort),
            ('frameloss', c_ushort),
            ('holds', c_ushort),
            ('rxvolts', c_ushort),
        ]

    blockdatatype = 0x7f


    def asdict(self):
        return {
            'A': self.A,
            'B': self.B,
            'L': self.L,
            'R': self.R,
            'frameloss': self.frameloss,
            'holds': self.holds,
            'rxvolts': self.rxvolts/100.0,
        }


def blockiterator(f):

    flightloghdr = FlightLogHeader()
    tagdate = BlockTag()
    blockdatatype = BlockDataType()
    datahdr = TLMDataHdr()
    data = TLMData()

    typemap = {(bt.blockdatatype, 0): bt() 
            for bt in (TLMRpmVoltData, TLMRxData)}

    bytesread = 0

    try:
        while True:

            blockoffset = bytesread

            n = f.readinto(tagdate)
            assert n == 4
            bytesread += n

            n = f.readinto(blockdatatype)
            assert n == 2
            bytesread += n

            rectype, datatype = blockdatatype.description
     
            if tagdate.isdata():
                # data records (start with a timestamp)
                datamap = typemap.get(blockdatatype.value, data)
                n = f.readinto(datamap)
                bytesread += n
                yield (blockoffset, tagdate.timestamp, rectype, datatype, 
                        datamap.asdict())
            else:
                # header records start with ffff ffff
                t1, t2 = blockdatatype.value
                if t1 != t2 and t2 != 0:
                    hdrmap = flightloghdr
                else:
                    hdrmap = datahdr

                n = f.readinto(hdrmap)
                bytesread += n
                yield (blockoffset, tagdate, rectype, datatype, 
                        hdrmap.asdict())
    except AssertionError as ae:
        print >> sys.stderr, "reached the end of the file"

   
def main():

    p = ArgumentParser()
    p.add_argument('--dir', help='''List all files with .TLM extension
in dir.''')
    p.add_argument('--logs', default='./logs', help='''Default location
        to store TLM flight logs (%(default)s).''')
    p.add_argument('--tlm', default='04450x Hite.TLM',
            help='Name of Spektrum TLM flight log to read (%(default)s).')
    p.add_argument('--csv', default='{date}{time}-{tlm}.csv',
            help='''CSV formatted data is written to filename.  Note this
output is much longer than the less structured default.  Filename can include
{date} and {time} which are expanded to yymmdd and hhmm respectively
(%(default)s.''')
    a = p.parse_args()

    now = datetime.datetime.now()
    meta = {'date': now.strftime('%y%m%d'),
        'time': now.strftime('%H%M')}

    if not os.path.exists(a.logs):
        os.makedirs(a.logs)

    tlmname = None

    if a.dir:
        tlms = glob.glob(os.path.join(a.dir, '*.TLM'))

        if not len(tlms):
            print >> sys.stderr, 'no TLM files found in "{0}"'.format(a.dir)
            return

        for i, tlm in enumerate(tlms):
            print '{0:2d}  {1}'.format(i, tlm)
        j = input('select file: ')

        srctlm = tlms[j]
        print 'file selected:', srctlm

        meta['tlm'] = os.path.splitext(os.path.basename(srctlm))[0]

        destname = '{date}{time}-{basename}'.\
                format(basename=os.path.basename(srctlm), **meta)
        desttlm = os.path.join(a.logs, destname)
        print desttlm

        print 'Copying "{0}" to "{1}"'.format(srctlm, desttlm)
        shutil.copyfile(srctlm, desttlm)

        tlmname = desttlm

    if not tlmname:
        tlmname = a.tlm
        meta['tlm'] = os.path.splitext(os.path.basename(tlmname))[0]

    with open(tlmname, 'rb') as ftlm:
        if a.csv:
            csvname = os.path.join(a.logs, a.csv.format(**meta))
            print 'using', csvname

            with open(csvname, 'w') as csv:
                flightno = 0
                csv.write('offset,flightno,timestamp,modelname,rectype,datatype,parameter,value')
                csv.write('\n')
                for n, timestamp, rectype, \
                        datatype, data in blockiterator(ftlm):
                    if datatype == 'flight start':
                        modelname = data['model name']
                        flightno += 1

                    for k, v in data.items():
                        csv.write(','.join([str(x) 
                                for x in (hex(n), flightno, timestamp, 
                                        modelname, rectype, datatype, k, v)]))
                        csv.write('\n')

        else:
            for n, timestamp, rectype, datatype, data in blockiterator(ftlm):
                print hex(n), timestamp, rectype, datatype, data


if __name__ == '__main__':
    main()


