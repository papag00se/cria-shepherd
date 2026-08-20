#include <cstdio>
#include <cuda_runtime.h>
#include <unistd.h>
int main(int argc,char**argv){
  int dev = argc>1 ? atoi(argv[1]) : 0;
  size_t f0,t0;
  cudaSetDevice(dev);
  cudaFree(0);                      // force context creation
  cudaMemGetInfo(&f0,&t0);
  printf("dev %d: cudaMemGetInfo AFTER context: total=%.0f MiB free=%.0f MiB used=%.0f MiB\n",
         dev, t0/1048576.0, f0/1048576.0, (t0-f0)/1048576.0);
  fflush(stdout);
  sleep(20);                        // hold so nvidia-smi can be sampled
  return 0;
}
