NVCC=/usr/local/cuda/bin/nvcc
NVDISASM=/usr/local/cuda/bin/nvdisasm
PYTHON=python3
CUDAFLAGS=-arch=sm_86


all: example.sass example_overlaid.sass

clean:
	-rm -f example.sass example_overlaid.sass

%.sass: %.cubin
	$(NVDISASM) -hex -c -novliw $< > $@

%_overlaid.sass: %.sass
	$(PYTHON) sassoverlay.py -s $< > $@

%.cubin: %.cu
	$(NVCC) -cubin -o $@ $(CUDAFLAGS) $<
