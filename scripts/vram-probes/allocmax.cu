#include <cstdio>
#include <cstdlib>
#include <vector>
#include <cuda_runtime.h>
static double MB(size_t b){return b/1048576.0;}
int main(int argc,char**argv){
  int dev=argc>1?atoi(argv[1]):0;
  cudaSetDevice(dev); cudaFree(0);
  size_t f,t; cudaMemGetInfo(&f,&t);
  printf("dev %d  total=%.0f  cudaMemGetInfo_free=%.0f\n",dev,MB(t),MB(f));
  std::vector<void*> p; size_t got=0;
  // descend: 256,64,16,4,1 MiB, then 256 KiB — squeezes out granularity loss
  size_t sizes[]={256ull<<20,64ull<<20,16ull<<20,4ull<<20,1ull<<20,256ull<<10};
  for(size_t s: sizes){
    size_t n=0; void* q;
    while(cudaMalloc(&q,s)==cudaSuccess){p.push_back(q);got+=s;n++;}
    cudaGetLastError();
    printf("   after %6.2f MiB chunks: +%zu allocs, cumulative %.1f MiB\n",MB(s),n,MB(got));
  }
  size_t f2,t2; cudaMemGetInfo(&f2,&t2);
  printf("dev %d  MAX ALLOCATED = %.1f MiB | cudaMemGetInfo_free_now=%.1f\n",dev,MB(got),MB(f2));
  printf("dev %d  total-max = %.1f MiB unreachable (driver Reserved is separately declared)\n",dev,MB(t)-MB(got));
  for(auto x:p)cudaFree(x);
  return 0;
}
