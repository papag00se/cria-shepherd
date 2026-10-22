cd /home/jesse/suite-runs/suite-feed-pipeline-java_ornith1.5_9b_codex_poff_1792678391-9qdq6kce && cat > tmp/Bench.java <<'EOF'
import org.apache.commons.csv.*;
import java.io.*;
import java.nio.charset.*;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;

public class Bench {
  static final String PATH = "data/feed.csv";
  static final CSVFormat FMT = CSVFormat.DEFAULT
      .withFirstRecordAsHeader(true)
      .withIgnoreEmptyLines(true)
      .withIgnoreHeaderCase(true)
      .withTrim(true)
      .withIgnoreSurroundingSpaces(true);

  static boolean isInteger(String s){ return s.length()>0 && s.chars().allMatch(c->c>='0'&&c<='9'); }
  static boolean isPrice(String s){
    String t=s.trim(); boolean hasDigit=false, hasDot=false;
    for(int i=0;i<t.length();i++){char c=t.charAt(i);
      if(Character.isDigit(c)){hasDigit=true;}
      else if(c=='-'||c=='+'||c=='.'||c=='$'||c=='€'||c=='£'||c=='%'){
        if((c=='-'||c=='+')&&i!=0)return false; if(c=='.'&&hasDot)return false;}
      else return false;}
    return hasDigit&&!hasDot||t.indexOf('.')<0;
  }

  // Version C: parse then accumulate directly, single-threaded
  static Map<String,Double> seqAccumulate() throws Exception {
    Map<String,Double> totals=new HashMap<>(); long rows=0;
    int sku=0,qty=2,price=3;
    try (CSVParser p=CSVFormat.DEFAULT.builder().setFirstRecordAsHeader(true)
        .setIgnoreEmptyLines(true).setIgnoreHeaderCase(true).setTrim(true)
        .setIgnoreSurroundingSpaces(true).parse(Files.newBufferedReader(Path.of(PATH),StandardCharsets.UTF_8))){
      List<String> header=p.getHeaderNames();
      for(CSVRecord r:p){
        if(r.size()<header.size()){continue;}
        String skuV=r.get(0),q=r.get(2),pp=r.get(3);
        if(skuV==null||skuV.isEmpty())continue;
        if(q==null||q.isEmpty())continue;
        if(!isInteger(q))continue;
        if(pp==null||pp.isEmpty())continue;
        if(!isPrice(pp))continue;
        totals.merge(skuV,Integer.parseInt(q)*Double.parseDouble(pp),Double::sum); rows++;
      }
    }
    return totals;
  }

  public static void main(String[] a) throws Exception {
    long t0=System.nanoTime();
    Map<String,Double> C=seqAccumulate();
    double t1=(System.nanoTime()-t0)/1e6;
    System.out.printf("C seqAccumulate: %.2f ms, skus=%d, rows=%d, sum=%.4f%n", t1, C.size(), 0L, C.values().stream().mapToDouble(Double::doubleValue).sum());
    // save reference
    try(PrintWriter w=new PrintWriter("tmp/ref_totals.txt")){
      List<String> keys=new ArrayList<>(C.keySet()); Collections.sort(keys);
      for(String k:keys) w.println(String.format("%s %.10f",k,C.get(k)));
    }
  }
}
EOF
CP=$(cat tmp/cp.txt); javac -cp "$CP" tmp/Bench.java && echo "compiled OK"