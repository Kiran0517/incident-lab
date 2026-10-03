package com.incidentlab.order;

public class DownstreamException extends RuntimeException {

    private final String dependency;

    public DownstreamException(String dependency, Throwable cause) {
        super(dependency + " call failed: " + cause.getMessage(), cause);
        this.dependency = dependency;
    }

    public String getDependency() {
        return dependency;
    }
}
