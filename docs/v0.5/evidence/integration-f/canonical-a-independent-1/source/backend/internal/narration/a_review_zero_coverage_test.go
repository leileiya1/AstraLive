package narration
import "testing"
func TestAReviewMissingTargetHashDoesNotGrantCanonicalCoverage(t *testing.T) {
 d:=fixture(t,2);s:=start(t,&d);must(t,d.CompleteNarration(proof(d,s),d.Revision,d.RunEpoch))
 target:=&d.Plan.Segments[1];target.FactIDs=[]string{"price"};target.Text="本商品当前标价是人民币99.00元。";target.TextHash=""
 d.State=Answering;d.Turn=&Turn{ID:"turn",MappedNarrationFacts:[]string{"price"},Answer:&Segment{ID:"answer",Text:"这款目前价格是人民币99.00元。",TextHash:Hash("这款目前价格是人民币99.00元。"),FactIDs:[]string{"price"},Lane:"AUDIENCE_ANSWER"}}
 d.Resume=&ResumePoint{NextSegmentID:target.ID,NextBeatID:target.BeatID}
 err:=d.CompleteAnswer(proof(d,*d.Turn.Answer),d.Revision,d.RunEpoch)
 if err==nil && (d.Plan.Segments[1].Status=="SATISFIED_BY_ANSWER" || contains(d.Cursor.CompletedFacts,"price")){t.Fatal("absent canonical map + missing target hash implicitly granted coverage")}
}
