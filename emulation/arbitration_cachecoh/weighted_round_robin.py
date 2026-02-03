# weighted_round_robin.py

class WeightedRoundRobinArbiter:
    """
    Weighted Round-Robin Arbiter
    
    Each requester has a weight that determines how many times it can be
    granted access before moving to the next requester. Higher weights
    receive more frequent grants.
    """
    
    def __init__(self, num_requesters, weights):
        """
        num_requesters: Number of requesters in the system
        weights: List of weights for each requester.
        """
        
        self.num_requesters = num_requesters
        
        if len(weights) != num_requesters:
            raise ValueError(f"Number of weights ({len(weights)}) must match " f"number of requesters ({num_requesters})")

        if any(w <= 0 for w in weights):
            raise ValueError("All weights must be positive integers")
        
        self.weights = list(weights)
        self.current_index = 0
        self.remaining_credits = self.weights[0]
    
    def arbitrate(self, requests):
        """
        Grant access to one requester based on weighted round-robin.
        
        Args:
            requests: List of 0s and 1s indicating which requesters are active
            
        Returns:
            List with single 1 indicating granted requester, or all 0s if no requests
        """
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
        max_attempts = self.num_requesters * max(self.weights)
        
        while attempts < max_attempts:
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
            self.current_index = (self.current_index + 1) % self.num_requesters
            self.remaining_credits = self.weights[self.current_index]
            attempts += 1
        
        # Fallback (should never reach here with valid inputs)
        return [0] * self.num_requesters
