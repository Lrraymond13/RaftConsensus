from enum import Enum 
from random import randint
import threading
import time
from queue import Queue 
import pudb
import pdb
import logging


#import logging and debugging 
logging.basicConfig(level=logging.DEBUG,
                    format='[%(levelname)s] (%(threadName)-10s) %(message)s',
                    )


from message import Message, Msg_Type

HEARTBEAT_TIMEOUT = 1



class State(Enum):
    follower = 1
    candidate = 2
    leader = 3


class Server(threading.Thread):
    def __init__(self, server_id, Raft_instance):
        #persistent attributes
        threading.Thread.__init__(self)
        self.ID = str(server_id)
        self.state = State.candidate
        self.daemon = True
        self.rlock = Raft_instance.rlock
        self.SERVER_IDS = Raft_instance.server_nums
        self.Raft_instance = Raft_instance

        self.current_term = 0
        self.voted_for = None
        self.log = list()
        #self.queue_messages = Queue()
        self.queue_messages= list()
        self.last_update = time.time()
        self.election_start = None
        self.election_time = self.generate_election_time()
        self.peers = [p for p in self.SERVER_IDS if p != self.ID]
        self.total_votes = 0

        #volatile attributes
        self.commit_index = None
        self.last_applied = 0

        #Leader attributes
        self.next_index = 0 
        self.match_index = 0

#generate election timeout interval
    def generate_election_time(self):
        #return randint(150,300)/1000
        return randint(15,300)/10

    def update_timers(self):
        #need to fix elapsed METHOD, throwing an error
        now = time.time()
        if self.state == State.candidate:
            try:
                elapsed = now - self.election_start
                #check for a dead leader, call election if leader dead
                if now - self.last_update > HEARTBEAT_TIMEOUT and self.state == State.follower:
                    self.call_election()
                #Election timer still not elapsed, check for messages- no action
                elif self.state == State.candidate and elapsed < self.election_time:
                    return
                    #check for messages
                #Election timer ran out, not converted to another state, request votes
                elif self.state == State.candidate and elapsed > self.election_time:
                    time.sleep(5)
                    self.call_election()
                #if follower check to make
                elif self.state == State.Leader:
                    self.send_heartbeat()

            #if election_start is still NONE, then this is first initialization
            except:
                self.call_election()
        if self.state == State.leader:
            self.send_heartbeat()


    def call_election(self):
        logging.debug("Calling Election %s" %self.ID) 
        #create random timer, when it times out, send out Request for Vote Messages
        #possibly clear message queue
        #clear election queue
        #self.queue_messages = Queue()
        self.queue_messages = list()
        self.election_time = self.generate_election_time()
        self.election_start = time.time()
     
        self.state = State.candidate
        self.voted_for = None
        self.current_term += 1

        self.request_votes()
        #self.state_manager.next_step()

    def request_votes(self):
        logging.debug("Asking for votes %s" %self.ID)
        #send message to all servers asking for votes
        self.send_message(recip = 'all_servers', msg_type = Msg_Type.RFV)

#sending vote function
    def send_vote(self):  
        logging.debug("sending vote: %s for: %s" %(str(self.ID), str(self.voted_for))) 
        with self.rlock:
            self.send_message(recip = [self.voted_for], msg_type = Msg_Type.RFV_YES) 

#process a heartbeat message
    def process_heartbeat(self, msg):
        logging.debug("processing heartbeat %s" %self.ID)
        #if get heartbeat, update time of last update
        if self.state == State.follower and msg.term >= self.current_term:
            self.last_update = time.time()
            #update term of the member if less than existing term
            self.current_term = msg.term
        #if current state is candidate, and term >= current, update to follower
        #this means the server is behind the other servers and needs to fast forward
        if self.state in [State.candidate, State.leader] and msg.term > self.current_term:
            self.last_update = time.time()
            self.current_term = msg.term
            self.state = State.follower
            self.voted_for = None
        else :
            return 
        #add check to only send heartbeat if no one in the global queue
        #if you receive a heartbeat from yourself, then send out another one to global queue
        #elif self.state == State.leader and msg.term == self.current_term:
            #if len(self.Raft_instance.message_queue) ==0 or str(self.Raft_instance.message_queue[0].sender) == str(self.server_id):
                #pass
           # else:
              #  self.send_heartbeat()
 

    def process_vote_request(self, msg):
        #print("processing vote request %s" %self.ID)
        if self.state == State.candidate and self.voted_for == None and msg.term >= self.current_term:
            self.voted_for = str(msg.sender)
            self.current_term = msg.term
            self.send_vote()


    def process_vote_response(self, msg): 
        #Calculate vote responses and add to tally to
        #calculate majority
        logging.debug("processing vote response %s" %self.ID)
        if self.state == State.candidate and msg.term == self.current_term :
            self.total_votes += 1
            logging.debug("total votes %s" %self.total_votes)
#become a leader if you receive a majority of your peers in votes
        if self.total_votes > len(self.peers)/2:
            self.state = State.leader
            self.current_term += 1
            self.become_leader()
#change state to leader
#send out heartbeat, clear your queue list
    def become_leader(self):
        logging.debug("becoming leader %s" %self.ID)
        self.send_heartbeat()
        #self.queue_messages = Queue()
        self.queue_messages = list()
        self.voted_for = None


    def send_heartbeat(self):
        logging.debug("Sending heartbeat %s" %self.ID)
        self.send_message(recip = 'all_servers', msg_type=Msg_Type.HEARTBEAT)


    def send_message(self, recip, msg_type):
        #Create a new message and add arguments
        logging.debug("Sending message %s to %s" %(str(self.ID), str(recip)))
        #Add message to universal queue
        #pass server IDS to the current message
        msg = Message(sender = self.ID, recipients = recip, msg_type = msg_type, term = self.current_term, server_ids = self.SERVER_IDS)

        #GLOBAL QUEUE ADD INFO
        with self.rlock:
            #adding message to Raft instance global queue
            #self.Raft_instance.message_queue.put(msg)
            self.Raft_instance.message_queue.append(msg)
            logging.debug("Adding to GLOBAL queue from %s"%self.ID)
    #organizing function for reading messages

    def check_messages(self):
        logging.debug("Checking Messages %s an len is %s" %(self.ID, len(self.queue_messages)))
        logging.debug(self.state)
        if len(self.queue_messages) == 0 and self.state == State.leader:
            self.send_heartbeat()
        while len(self.queue_messages) > 0 :
            self.process_message(self.queue_messages.pop())

       # while not self.queue_messages.empty():
         #   self.process_message(self.queue_messages.get())
            
            #remove message if term is < current ter

    def process_message(self, msg):
        #remove old messages from queue
        logging.debug("Processing messages %s" %self.ID)    
        if msg.term < self.current_term:
            print("No messages")
            return
        if msg.type == Msg_Type.HEARTBEAT:

            self.process_heartbeat(msg)

        elif msg.type == Msg_Type.RFV:
            self.process_vote_request(msg)

        elif msg.type == Msg_Type.RFV_YES:
            self.process_vote_response(msg)

        else:
            print("Bad")

    def run(self):
        #while self.Raft_instance.Run:
        while True:
            logging.debug("thread updating timers")
            self.update_timers()
            logging.debug("thread checking messages")
            self.check_messages()




if __name__ == '__main_u_':

    GLOBAL_QUEUE = Queue()
    rlock = threading.RLock()
    test_msg = Message('234', ['123', '234'], Msg_Type.HEARTBEAT, 1)
    test_server = Server('123', rlock)
    test_server.call_election()
    pdb.set_trace()







