NVCC=/usr/local/cuda/bin/nvcc
NVDISASM=/usr/local/cuda/bin/nvdisasm
PYTHON=python3
CUDAFLAGS=-arch=sm_86


all: example.sass example.sass_overlaid

clean:
	-rm -f example.sass example.sass_overlaid

%.sass: %.cubin
	$(NVDISASM) -hex -c -novliw $< > $@

%.sass_overlaid: %.sass
	$(PYTHON) sassoverlay.py -s $< > $@

%.cubin: %.cu
	$(NVCC) -cubin -o $@ $(CUDAFLAGS) $<
