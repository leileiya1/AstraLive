package main
import("astralive/backend/internal/durability";"encoding/json";"os")
type V struct{Name string `json:"name"`;Timeline bool `json:"timeline"`;Raw string `json:"raw"`;Valid bool `json:"valid"`}
func main(){b,_:=os.ReadFile(os.Args[1]);var vs []V;json.Unmarshal(b,&vs);out:=[]map[string]any{};for _,v:=range vs{var hash string;var err error;if v.Timeline{hash,err=durability.TimelineHash([]byte(v.Raw))}else{hash,err=durability.Hash([]byte(v.Raw))};out=append(out,map[string]any{"name":v.Name,"accepted":err==nil,"hash":hash});if (err==nil)!=v.Valid{panic(v.Name)}};json.NewEncoder(os.Stdout).Encode(out)}
