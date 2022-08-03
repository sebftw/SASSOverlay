NVCC=/usr/local/cuda/bin/nvcc
NVDISASM=/usr/local/cuda/bin/nvdisasm
PYTHON=python3
CUDAFLAGS=-arch=sm_86


all: example.sass

clean:
	-rm -f $(targets)

%.sass: %.cubin
	$(NVDISASM) -hex -c -novliw $< | $(PYTHON) sassoverlay.py -s > $@

%.cubin: %.cu
	$(NVCC) -cubin -o $@ $(CUDAFLAGS) $<
