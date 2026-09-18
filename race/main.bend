# A server that gives each connection 500 ms to speak. A client that
# connects and says nothing gets a 408 and is closed; one that sends a
# request gets a 200. Try it:
#   bend main.bend -o race && ./race
import Base

def TCP.recv_timeout(sock: Socket, max: U32, ms: U32) -> IO(Socket & Result<&1, &1, U32 & String, String>):
  import "./tcp_recv_timeout.c"
  import "./tcp_recv_timeout.js"

def sent(m: Socket & Result<&1, &1, U32 & String, Unit>) -> IO(Unit):
  (s, r) = m
  Socket.close(s)

def timeout_response(+text: String) -> String:
  "HTTP/1.1 408 Request Timeout\r\nContent-Length: " ++ Nat.show(String.length(text)) ++ "\r\nConnection: close\r\n\r\n" ++ text

def reply(m: Socket & Result<&1, &1, U32 & String, String>) -> IO(Unit):
  (s, r) = m
  match r:
    case Done{req}:
      do IO<Unit>:
        m2 : Socket & Result<&1, &1, U32 & String, Unit> <- TCP.send(s, "HTTP/1.1 200 OK\r\nContent-Length: 3\r\nConnection: close\r\n\r\nok\n")
        sent(m2)
    case Fail{(code, text)}:
      do IO<Unit>:
        m2 : Socket & Result<&1, &1, U32 & String, Unit> <- TCP.send(s, timeout_response(text))
        sent(m2)

def talk(s: Socket) -> IO(Unit):
  do IO<Unit>:
    m : Socket & Result<&1, &1, U32 & String, String> <- TCP.recv_timeout(s, 4096, 500)
    reply(m)

def conn(m: Listener & Result<&1, &1, U32 & String, Socket>) -> IO(Listener):
  (l, r) = m
  do IO<Listener>:
    s : Socket <- IO.pass(Socket, r)
    IO.spawn(Unit, talk(s))
    return l

@unsafe
def serve(l: Listener) -> IO(Unit):
  do IO<Unit>:
    m  : Listener & Result<&1, &1, U32 & String, Socket> <- TCP.accept(l)
    l2 : Listener <- conn(m)
    serve(l2)

def main() -> IO(Unit):
  do IO<Unit>:
    l : Listener <- IO.try(Listener, TCP.listen(8087))
    IO.print("race demo on 8087")
    serve(l)
