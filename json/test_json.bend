import Base
import ./json.bend as Json

def sample() -> Json.Json:
  Json.JObj{[Json.JMember{"event", Json.JStr{"Kapitularz"}}, Json.JMember{"sessions", Json.JArr{[Json.JNum{1000}, Json.JNull{}, Json.JBool{True{}}]}}, Json.JMember{"note", Json.JStr{"say \"hi\"\n"}}]}

# LAW: the sample prints as this exact text. The law spends explicit
# fuel: the checker walks a Nat one step at a time, so show's runtime
# fuel would take it a hundred million steps to reach the same answer.
law show_sample:
  {Json.print.go(64n, Json.One{sample()}) == "{\"event\":\"Kapitularz\",\"sessions\":[1000,null,true],\"note\":\"say \\\"hi\\\"\\n\"}" : String}

def show_sample():
  {==}

def main() -> IO(Unit):
  IO.print(Json.show(sample()))
