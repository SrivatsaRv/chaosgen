#!/bin/bash
# Sock Shop Deployment Script
# Deploys the complete Sock Shop microservices application to Kubernetes

set -e

echo "🚀 Deploying Sock Shop to Kubernetes..."

# Create namespace
echo "📦 Creating sock-shop namespace..."
kubectl create namespace sock-shop --dry-run=client -o yaml | kubectl apply -f -

# Deploy Sock Shop using the official manifests
echo "📋 Deploying Sock Shop services..."
kubectl apply -f https://raw.githubusercontent.com/microservices-demo/microservices-demo/master/deploy/kubernetes/complete-demo.yaml

# Wait for all pods to be ready
echo "⏳ Waiting for all pods to be ready..."
kubectl wait --for=condition=ready pod -l app=front-end -n sock-shop --timeout=300s
kubectl wait --for=condition=ready pod -l app=catalogue -n sock-shop --timeout=300s
kubectl wait --for=condition=ready pod -l app=carts -n sock-shop --timeout=300s
kubectl wait --for=condition=ready pod -l app=orders -n sock-shop --timeout=300s
kubectl wait --for=condition=ready pod -l app=user -n sock-shop --timeout=300s
kubectl wait --for=condition=ready pod -l app=payment -n sock-shop --timeout=300s
kubectl wait --for=condition=ready pod -l app=shipping -n sock-shop --timeout=300s

# Get service URLs
echo "🌐 Sock Shop is deployed!"
echo ""
echo "📊 Service Status:"
kubectl get pods -n sock-shop

echo ""
echo "🔗 Access URLs:"
echo "Frontend: http://localhost:30001"
echo "Catalogue API: http://localhost:30002"
echo "Cart API: http://localhost:30003"
echo "Orders API: http://localhost:30004"
echo "User API: http://localhost:30005"
echo "Payment API: http://localhost:30006"
echo "Shipping API: http://localhost:30007"

echo ""
echo "📝 To expose services locally, run:"
echo "kubectl port-forward -n sock-shop svc/front-end 30001:80"
echo "kubectl port-forward -n sock-shop svc/catalogue 30002:80"
echo "kubectl port-forward -n sock-shop svc/carts 30003:80"
echo "kubectl port-forward -n sock-shop svc/orders 30004:80"
echo "kubectl port-forward -n sock-shop svc/user 30005:80"
echo "kubectl port-forward -n sock-shop svc/payment 30006:80"
echo "kubectl port-forward -n sock-shop svc/shipping 30007:80"

echo ""
echo "✅ Sock Shop deployment complete!"
echo "🎯 You can now run chaos experiments with: python demo.py" 