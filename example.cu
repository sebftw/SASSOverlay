__global__ void kernel(float *out, int N) {
	#pragma unroll 1
	for(int i = 0; i < N; i++)
		out[i] += 5;
}
