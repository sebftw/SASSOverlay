# SASSOverlay
Utility to add control code information to the output of `nvdisasm` or `cuobjdump`.

This way, one can see the number of fixed-latency stall cycles, as well as how the six barriers for variable-latency instructions are used.
Works for Maxwell-like (5.x, 6.x) and Volta-like (7.x, 8.x) architectures.


Suggested usage:
```
nvcc -arch=sm_86 -cubin example.cu
nvdisasm -hex -c -novliw example.cubin > example.sass
python3 sassoverlay.py -s example.sass > example_overlaid.sass
```
The argument -s is to suppress the hex codes. 
A snippet of the generated output:
```
  /*0000*/      IMAD.MOV.U32 R1, RZ, RZ, c[0x0][0x28] ;        // [ 2 Y ]
  /*0010*/      IMAD.MOV.U32 R0, RZ, RZ, c[0x0][0x168] ;       // [ 5 Y ]
  /*0020*/      ISETP.GE.AND P0, PT, R0, 0x1, PT ;             // [13 Y ]
  /*0030*/ @!P0 EXIT ;                                         // [ 5   ]
  /*0040*/      MOV R4, c[0x0][0x160] ;                        // [ 1   ]
  /*0050*/      IMAD.MOV.U32 R7, RZ, RZ, c[0x0][0x164] ;       // [ 1   ]
  /*0060*/      MOV R0, RZ ;                                   // [ 1   ]
  /*0070*/      ULDC.64 UR4, c[0x0][0x118] ;                   // [ 2 Y ]
.L_x_0:
  /*0080*/      IMAD.MOV.U32 R2, RZ, RZ, R4 ;                  // [ 1   |         000001 ]
  /*0090*/      MOV R3, R7 ;                                   // [ 5 Y ]
  /*00a0*/      LDG.E R4, [R2.64] ;                            // [ 1   | WR3            ]
  /*00b0*/      IADD3 R0, R0, 0x1, RZ ;                        // [ 4 Y ]
  /*00c0*/      ISETP.GE.AND P0, PT, R0, c[0x0][0x168], PT ;   // [ 1   ]
  /*00d0*/      FADD R5, R4, 5 ;                               // [ 1   |         000100 ]
  /*00e0*/      IADD3 R4, P1, R2, 0x4, RZ ;                    // [ 4 Y ]
  /*00f0*/      STG.E [R2.64], R5 ;                            // [ 1   |     RD1        ]
  /*0100*/      IMAD.X R7, RZ, RZ, R3, P1 ;                    // [ 6 Y ]
  /*0110*/ @!P0 BRA `(.L_x_0) ;                                // [ 5   ]
  /*0120*/      EXIT ;                                         // [ 5   ]
```
It can be seen that the latency for ISETP is 13 cycles. Y is for yield, meaning the scheduler is made to favor switching to another warp. Maxwell-like architectures can in some cases dual-issue (two instructions in one clock), which is seen with a latency of 0.


Then WRX is to protect against read-after-write hazards (I.e. variable latency), and RDX to protect against write-after-read issues (STG has delayed access to R2, so the address in R2 may not be overwritten before it has been read). Lastly, the bitfield of 6 values is where instructions are made to wait (Instruction 0080 waits for 00f0, and 00d0 waits for 00a0) - it is a bitfield as one instruction can wait for more than one barrier.

This insight into the inner workings of the [Instruction Scheduling](https://en.wikipedia.org/wiki/Instruction_scheduling) can be used to guide optimizations.
