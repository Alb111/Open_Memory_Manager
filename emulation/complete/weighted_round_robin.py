from axi_request import axi_request
from typing import List, Callable, Optional

class WeightedRoundRobinArbiter:

    def __init__(self, num_requesters: int, weights: List[int], axi_handler: Callable[[axi_request], axi_request]):
 
        # error checking
        if len(weights) != num_requesters:
            raise ValueError(f"Number of weights ({len(weights)}) must match " f"number of requesters ({num_requesters})")

        if any(w <= 0 for w in weights):
            raise ValueError("All weights must be positive integers")

        
        # num_requesters: Number of requesters in the system
        self.num_requesters = num_requesters
                
        # weights: List of weights for each requester, defines how many
        # times a requester gets prioroty
        self.weights = weights

        # current requester index
        self.current_index = 0

        # their reminading credits/tickets
        self.remaining_credits = self.weights[0]

        # area to send chossen axi call to
        self.axi_send_and_recieve: Callable[[axi_request], axi_request] = axi_handler

        # find max possible iterations needed for round bin
        self.max_possible_iterations: int = sum(weights)

        # bit mapping to track that all cores requested
        self.cores_arrived: List[int] = [0] * self.num_requesters
        self.cores_axi_requsts: List[Optional[axi_request]] = [None] * self.num_requesters
        

    def axi_handler_arbiter(self, request_axi: axi_request, core_id: int ) -> Optional[axi_request]:

        # mark core as arrived and store its data
        self.cores_arrived[core_id] = 1
        self.cores_axi_requsts[core_id] = request_axi

        # all cores arrived
        if sum(self.cores_arrived) == self.num_requesters:

            # build requests arr from axi_arr
            requests_in: List[int] = [] 
            for axi_request in self.cores_axi_requsts:
                # need this cause axi_arr doesnt force type
                if axi_request is None:
                    raise ValueError("axi_requests None")

                requests_in.append(axi_request.mem_valid)

            # send this into nick arbitrate function
            requests_out: List[int] = self.arbitrate(requests_in)

            # go through results
            for core_i, request_valid in enumerate(requests_out):

                curr_cores_axi_request: Optional[axi_request] = self.cores_axi_requsts[core_i]
                # make sure axi_packet isnt None
                if curr_cores_axi_request is None:
                    raise ValueError("axi_requests None")
                
                # abitrate said yes 2 this core
                if request_valid == 1:
                    print("sent data to memory")
                    return self.axi_send_and_recieve(curr_cores_axi_request)

                # abitrate said no 2 this core
                else:
                    return curr_cores_axi_request

        # not all core have arrived
        else:
            return request_axi

                                
    def arbitrate(self, requests: List[int]) -> List[int]:

        # error checker
        if len(requests) != self.num_requesters:
            raise ValueError(
                f"Number of requests ({len(requests)}) must match "
                f"number of requesters ({self.num_requesters})"
            )
        
        # If no requests, return all zeros
        if sum(requests) == 0:
            return [0] * self.num_requesters
        

        # Search for the next requester with an active request
        attempts = 0
        while attempts < self.max_possible_iterations:

            # If current requester has a request, grant it
            if requests[self.current_index] == 1:
                grant = [0] * self.num_requesters
                grant[self.current_index] = 1
                
                # Decrement credits
                self.remaining_credits -= 1
                
                # Move to next requester if credits exhausted
                if self.remaining_credits == 0:
                    self.current_index = (self.current_index + 1) % self.num_requesters
                    self.remaining_credits = self.weights[self.current_index]
                
                return grant

            # Current requester has no request, move to next
            else:
                self.current_index = (self.current_index + 1) % self.num_requesters
                self.remaining_credits = self.weights[self.current_index]
                attempts += 1
        
        # Fallback (should never reach here with valid inputs)
        print("error ")
        raise Exception("abritation hit timeout")
