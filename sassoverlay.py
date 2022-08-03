#!/usr/bin/python
import fileinput
import sys
import re
import argparse
import itertools
from collections import OrderedDict

# /usr/local/cuda/bin/cuobjdump /usr/local/cuda/targets/x86_64-linux/lib/libcublas.so -xelf all -arch=sm_86
# hex_pattern = re.compile("/\* (0x[0-9a-f]+) \*/")  # <- Match the commented hex value of the instruction/control code.
#pattern = re.compile(';?\s*/(\*) (0x[0-9a-f]+) (\*)/') # <- Match the commented hex value of the instruction/control code.
pattern = re.compile(r'(/\*([0-9a-f]+)\*/\s*(@P\d+)?\s*(.+);)?\s*/\* (0x[0-9a-f]+) \*/') # <- Match the commented hex value of the instruction/control code.
hex_group = 5  #  ^ The capture group of the instruction hex code.
inst_group = hex_group - 1

def handle_arguments():
    parser = argparse.ArgumentParser(
        description='Augment the output of cuobjdump or nvdisasm.',
        usage='Supply the output of cuobjdump or nvdisasm with the "-hex -novliw" arguments to this program. \n'
              'Example with pipes "./nvdisasm_overlay.py | nvdisasm -hex program.cubin"\n'
              'Example with file input "./nvdisasm_overlay.py program_disasm.txt"\n',
        epilog = 'The format is of fields is [ FIXED LATENCY | VARIABLE LATENCY | OTHER ] '
                 'where FIXED LATENCY contains the number of stall cycles and "Y" if yield is done. '
                 'VARIABLE LATENCY contains the write and read barrier setters, as well as the barrier consumption shown as 6 bits. '
                 'The WRITE/WR barrier is used to handle variable latency (RAW/WAW hazards). '
                 'The READ/RD barrier is used to prevent write after read hazards (aka WAR or "Anti"). '
                 'There are 6 barriers.'
                 )

    parser.add_argument('-s', '--suppress-hex', action='store_true')

    return parser.parse_known_args()

def ffs(x):
    """Returns the index, counting from 0, of the
    least significant set bit in `x`.
    """
    # from https://stackoverflow.com/a/36059264
    return (x&-x).bit_length()-1


def bit_count(x):
    return bin(x).count("1")


class Maxwell:
    mask = 0b111111111111111111111 # = (1<<21)-1
    bundled_control = True
    fields = [5, 3, 3, 6, 3, 1]
    # The last field is given as a width of 3 in the T4 paper, but I think it is only 3 bits wide.
    # field_masks = get_field_masks(fields)

    @staticmethod
    def style(self):
        return self.old, self.mask

    @staticmethod
    def pretty_control(control_values, opcode=None):
        stall = control_values[0]
        yield_flag = 'Y'
        # If the yield flag is used (meaning the yield bit is zero), stall counts up to 15 are supported.
        # stall = 16 = 0b10000 is not supported, as this is the yield bit.
        if stall & 0b10000:
            yield_flag = '' # '-'
            stall -= 16
            # Then it appears stall up to 11 is used without yield (e.g. in case of register reuse)
            #  - Stall values with yield above 11 are supported, but they seem to have a special meaning.
            #  - Specifically it seems the stall values 13 (and 14) are named YIELD.
        wr = ''
        if control_values[1] != 7:
             # WR
             wr = 'WR'+str(control_values[1]+1)

        rd = ''
        if control_values[2] != 7:
            # RD
            rd = 'RD'+str(control_values[2]+1)

        req = ''
        if control_values[3] != 0:
            #if bit_count(control_values[3]) == 1:
                # If only one barrier is in use, just print its value.
            #    req = str(ffs(control_values[3]))
            #else:
            req = '{0:06b}'.format(control_values[3])

        #coupled_flag = 'C' if control_values[5] != 0 else ''
        if wr or rd or req:
            return '[{:>2s} {:1s} | {:3s} {:3s} {:6s} ]'.format(str(stall), yield_flag, wr, rd, req)
        else:
            return '[{:>2s} {:1s} ]'.format(str(stall), yield_flag, wr, rd, req)

    @classmethod
    def decode_control(cls, control_code):
        values = []
        for field in cls.fields:
            value = control_code & ((1<<field)-1)
            control_code >>= field
            values.append(value)

        return values

class Turing(Maxwell):
    # A 26 bit control code, which is stored in the leading bits of the 64 bit word.
    fields = [2, 1, 5, 3, 3, 6, 3, 3]
    bit_count = sum(fields)
    mask = ((1<<bit_count)-1) << (64-bit_count)
    bundled_control = False
    # "Barriers take one additional clock cycle to become active on top of the clock consumed by the instruction doing the setting" - https://github.com/NervanaSystems/maxas/wiki/Control-Codes
    RD_inst = {'LDS', 'BMMA', 'DADD', 'F2F', 'NANOTRAP', 'SULD', 'LDSM', 'SETLMEMBASE', 'DFMA', 'CCTL', 'SUST', 'I2F',
               'GETLMEMBASE', 'RED', 'TLD4', 'REDUX', 'HMMA', 'MEMBAR', 'TMML', 'ALD', 'B2R', 'LDGDEPBAR', 'S2R',
               'SUATOM', 'BAR', 'TXQ', 'F2I', 'IMMA', 'TEX', 'IPA', 'BMOV', 'CLMAD', 'FOOTPRINT', 'STL', 'ATOMS', 'ST',
               'CCTLT', 'SETCTAID', 'R2B', 'LDC', 'LD', 'ISBEWR', 'SHFL', 'LDL', 'LDGSTS', 'OUT', 'AL2P', 'TLD',
               'PIXLD', 'S2UR', 'FRND', 'DMMA', 'BREV', 'ATOM', 'STG', 'DMUL', 'AST', 'MOVM', 'LDG', 'ATOMG', 'STS',
               'FCHK', 'TXD', 'FLO', 'POPC', 'ARRIVES', 'CCTLL', 'MATCH', 'LDTRAM', 'ISBERD', 'R2UR', 'MUFU', 'SUQUERY',
               'QSPC', 'SURED', 'DSETP', 'TTUST'}

    not_REQ_inst = {'TTUGO', 'TTUCLOSE', 'TTULD', 'TTUST'}

    WR_inst = {'ALD', 'ATOMG', 'LDS', 'BMMA', 'DADD', 'B2R', 'F2F', 'LDGDEPBAR', 'S2R', 'TTUCLOSE', 'LD', 'SUATOM',
               'FCHK', 'SHFL', 'LDSM', 'SULD', 'TXQ', 'TTULD', 'LDL', 'LDGSTS', 'TXD', 'F2I', 'IMMA', 'DFMA', 'FLO',
               'TEX', 'IPA', 'OUT', 'POPC', 'BMOV', 'AL2P', 'CLMAD', 'TLD', 'MATCH', 'PIXLD', 'LDTRAM', 'ISBERD',
               'S2UR', 'R2UR', 'FRND', 'MUFU', 'SUQUERY', 'I2F', 'QSPC', 'DMMA', 'GETLMEMBASE', 'BREV', 'FOOTPRINT',
               'ATOMS', 'ATOM', 'TLD4', 'SETCTAID', 'DSETP', 'REDUX', 'HMMA', 'DMUL', 'TMML', 'LDC', 'MOVM', 'LDG'}

    batch_values = {1: 'START', 2:'S_TILE', 3:'INVALI', 4: 'END', 5: 'EXEMPT'}

    @classmethod
    def pretty_control(cls, control_values, opcode=None):
        # print(control_values)

        del control_values[1]   # Remove unused bits
        del control_values[-1]
        opex = control_values[1] | (control_values[-1] << 5)
        #  0b10000 * (opex_upper & 1) + opex_lower>>1
        #print(control_values, opex>>1, opex)
        # print(control_values, opex)
        #print(control_values,)
        pm = ''
        if control_values[0] != 0:
            pm = 'PM{:d}'.format(control_values[0])

        # BATCH_T "NOP"=0 , "BARRIER_EXEMPT"=5 , "BATCH_START_TILE"=2 , "BATCH_START"=1 , "BATCH_END"=4;
        batch = ''
        if control_values[-1] != 0 and not (control_values[1] & 0b10000):
            # BATCH appears to be a feature that can be stored in the reuse bits whenever the yield flag is on.
            # One cannot reuse registers while yielding, so this makes sense.
            batch = cls.batch_values[control_values[-1]]

            #batch = 'BATCH{:d}'.format(control_values[-1])

        if opcode not in cls.WR_inst and control_values[2] != 7:
            # In this case it appears the bits may still have values in them, but certainly not for the purpose of RD/WR barriers.
            # Not sure how/why, as the instruction description seems to specify it must be value 7 for these.
            # TODO: Try and modify this field and see if nvdisasm ignores it or not?
            # print('wat', control_values[2], opcode)
            # control_values[2] = 7
            pass

        if opcode not in cls.RD_inst: #and control_values[3] == 0:
            # control_values[3] = 7
            pass


        if opcode in cls.not_REQ_inst:  #and control_values[4] == 0:
            # control_values[4] = 0
            pass


        last = ''
        stall = control_values[1]
        yield_flag = 'Y'
        if stall & 0b10000:
            yield_flag = ''  # '-'
            stall -= 16
            # control_values[-1] = 0

        #if control_values[-1]:
        #    last = '{0:03b}'.format(control_values[-1])

        # print(control_values[4]) '{0:03b} {0:05b}'.format(control_values[-1], control_values[1])
        # print(opcode)
        pp = Maxwell.pretty_control(control_values[1:] + [0])
        # [1:4], pp[5:]

        # control_values[-1], control_values[1]
        if batch or pm:
            return '{:s} | {:6s} {:3s} ]'.format(pp[:-2], batch, pm)
        else:
            return pp



def discover_arch(lines):
    consumed_lines = []
    status = []
    for line in lines:
        consumed_lines.append(line)
        match = pattern.search(line)
        if match is not None:
            is_instruction_line = match.group(4) is not None
            if status and is_instruction_line == status[0]:
                break
            status.append(is_instruction_line)

    if status == [True, False]:
        # Turing and beyond is encoded as one instruction packed into two 64-bit words.
        arch = Turing
    elif status == [False, True, True, True]:
        # Maxwell and the like is a control code bundle followed by the three instructions it provides control for.
        arch = Maxwell

    return arch, consumed_lines

def overlay(lines, arch=None):
    prev_code = 0
    # Run through lines in the given input files or the stdin.
    prev_line = None
    control_bundle = 0
    opcode = None

    # Discover architecture.
    if arch is None:
        arch, consumed_lines = discover_arch(lines)
        # "un-consume" the lines by placing them in front of the line stream again.
        lines = itertools.chain(consumed_lines, lines)


    # fileinput.input(remaining_args)
    for line in lines:
        match = pattern.search(line)

        if match is None:
            # In this case just pass - through.
            yield line  # sys.stdout.write(line)
            continue
        code = int(match.group(hex_group), 16)  # Get the hex code value.

        # Every instruction ends with ; and is followed by the hex code output.
        is_instruction_line = match.group(4) is not None  # match.group(1)[-1] == ';'
        if is_instruction_line:
            opcode = match.group(4).split()[0].split('.')[0]

        # if arch.bundled_control:
        # On older architectures, the control information for multiple instructions are collected in "bundles".
        if not is_instruction_line:  # or not arch.bundled_control:
            # This is a control code bundle.
            control_bundle = code

        control_code = control_bundle & arch.mask  # Get the bits corresponding to control code information.
        control_code = control_code >> ffs(arch.mask)  # Remove the trailing zeroes.
        if is_instruction_line and arch.bundled_control:
            # Shift to the next part of control code bundle.
            control_bundle = control_bundle >> bit_count(arch.mask)
        # print(bin(control_bundle), bin(code))

        if args.suppress_hex and (not is_instruction_line and arch.bundled_control):
            continue

        if args.suppress_hex or not arch.bundled_control:
            line = line[:match.start(hex_group) - 3] + line[match.end(hex_group) + 3:].rstrip()
        else:
            line = line.rstrip()

        # control_string = 'A'
        print_now = False
        if is_instruction_line and arch.bundled_control:
            print_now = True
            # opcode = opcode.split()[0].split('.')[0]
            # control_string = str(arch.pretty_control(arch.decode_control(control_code), opcode))
            # sys.stdout.write(line + ' ' + control_string + '\n')
        elif not arch.bundled_control and not is_instruction_line:
            print_now = True
            if not args.suppress_hex:
                prev_line = prev_line + '/* 0x{:032x} */'.format((code << 64) + prev_code)

        if print_now:
            control_string = str(arch.pretty_control(arch.decode_control(control_code), opcode))
            line_print = prev_line
            if arch.bundled_control:
                line_print = line
            # sys.stdout.write
            yield line_print + ' // ' + control_string + '\n'

        prev_line = line
        prev_opcode = opcode
        prev_code = code


if __name__ == "__main__":
    # Thanks to https://arxiv.org/pdf/1903.07486.pdf for a good description of the encoding.
    args, remaining_args = handle_arguments()
    
    for line_overlaid in overlay(fileinput.input(remaining_args)):
        sys.stdout.write(line_overlaid)
    
